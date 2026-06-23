"""
/sophia - Quick access to the Sophia orchestrator agent.
Creates a default Sophia agent if one doesn't exist yet, then starts a task.
"""
import logging
import os

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core import orchestrator
from core import workspace as ws_mod
from storage import db
from bot import keyboards

log = logging.getLogger(__name__)
router = Router()

SOPHIA_WORKSPACE_PATH = "/workspaces/sophia"
SOPHIA_WORKSPACE_NAME = "sophia_meta"


class SophiaTaskForm(StatesGroup):
    prompt = State()


async def _get_or_create_sophia() -> str:
    """Return the agent_id of the most recent Sophia agent, creating one if needed."""
    row = await db.fetchone(
        "SELECT id FROM agents WHERE role='orchestrator' ORDER BY created_at DESC LIMIT 1"
    )
    if row:
        return row["id"]

    # Create the default Sophia workspace
    os.makedirs(SOPHIA_WORKSPACE_PATH, exist_ok=True)
    ws_row = await db.fetchone(
        "SELECT id FROM workspaces WHERE name=?", (SOPHIA_WORKSPACE_NAME,)
    )
    if ws_row:
        ws_id = ws_row["id"]
    else:
        ws_id = await ws_mod.create_workspace(SOPHIA_WORKSPACE_NAME, SOPHIA_WORKSPACE_PATH)

    # Get Sophia template
    tpl = await db.fetchone("SELECT system_prompt FROM templates WHERE name='Sophia' LIMIT 1")
    system_prompt = tpl["system_prompt"] if tpl else (
        "You are Sophia, the SOPHIA orchestration agent. "
        "Analyze user requests and spawn specialist agents using [[SOPHIA:...]] commands."
    )

    agent = await orchestrator.create_agent(
        name="Sophia",
        role="orchestrator",
        system_prompt=system_prompt,
        workspace_id=ws_id,
        settings={"skip_permissions": True},
    )
    log.info("Created default Sophia agent: %s", agent.agent_id)
    return agent.agent_id


@router.message(Command("sophia"))
async def cmd_sophia(msg: Message, state: FSMContext) -> None:
    agent_id = await _get_or_create_sophia()
    row = await db.fetchone("SELECT name, status FROM agents WHERE id=?", (agent_id,))
    status = row["status"] if row else "idle"

    if status == "running":
        await msg.answer(
            "🎭 <b>Sophia is already running a task.</b>\n\n"
            "Wait for her to finish or use /agents to check her status.",
            parse_mode="HTML",
            reply_markup=keyboards.back_to_menu(),
        )
        return

    await state.update_data(sophia_agent_id=agent_id)
    await state.set_state(SophiaTaskForm.prompt)
    await msg.answer(
        "🎭 <b>Sophia - Orchestration Agent</b>\n\n"
        "Tell me what you want to build or accomplish.\n"
        "I'll analyze your request, create the right workspace and agents, "
        "and get them working automatically.\n\n"
        "<i>Examples:</i>\n"
        "• Build a REST API for managing tasks with tests\n"
        "• Create a price scraper for e-commerce sites\n"
        "• Set up a monitoring script for server health\n\n"
        "What do you need?",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(SophiaTaskForm.prompt)
async def sophia_task_prompt(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    prompt = msg.text.strip()
    data = await state.get_data()
    agent_id = data.get("sophia_agent_id")

    if not agent_id:
        agent_id = await _get_or_create_sophia()

    ok = await orchestrator.start_agent(agent_id, prompt, msg.chat.id)
    await state.clear()
    if ok:
        await msg.answer(
            "🎭 <b>Sophia is on it!</b>\n\n"
            "She'll analyze your request and automatically set up the project.\n"
            "Watch for workspace creation, agent spawning, and task output below.",
            parse_mode="HTML",
        )
    else:
        await msg.answer(
            "⚠️ Sophia is already busy. Use /agents to check her status.",
            parse_mode="HTML",
            reply_markup=keyboards.back_to_menu(),
        )


@router.callback_query(F.data == "menu_sophia")
async def cb_menu_sophia(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await cmd_sophia(cb.message, state)
