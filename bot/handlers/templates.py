import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from storage import db
from bot import keyboards

log = logging.getLogger(__name__)
router = Router()


class NewTemplateForm(StatesGroup):
    name          = State()
    description   = State()
    system_prompt = State()


@router.message(Command("templates"))
async def cmd_templates(msg: Message) -> None:
    tpls = await db.fetchall("SELECT * FROM templates ORDER BY is_builtin DESC, name")
    if not tpls:
        await msg.answer("<b>📋 Templates</b>\n\nNo templates found.", parse_mode="HTML",
                         reply_markup=keyboards.back_to_menu())
        return
    lines = ["<b>📋 Role Templates</b>\n"]
    for t in tpls:
        icon = "⭐" if t["is_builtin"] else "✏️"
        lines.append(f"{icon} <b>{t['name']}</b> - {t['description'] or ''}")
    lines.append("\n<i>Tap a template to view or use it.</i>")
    await msg.answer("\n".join(lines), parse_mode="HTML",
                     reply_markup=keyboards.templates_list_keyboard(tpls))


@router.message(Command("template"))
async def cmd_template_detail(msg: Message) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await msg.answer("Usage: /template <name>")
        return
    name = parts[1].strip()
    row = await db.fetchone("SELECT * FROM templates WHERE name = ?", (name,))
    if not row:
        await msg.answer(f"Template '{name}' not found.")
        return
    tag = "⭐ built-in" if row["is_builtin"] else "✏️ custom"
    await msg.answer(
        f"<b>📋 {row['name']}</b> [{tag}]\n\n"
        f"<i>{row['description'] or ''}</i>\n\n"
        f"<b>System Prompt:</b>\n<pre>{row['system_prompt'][:800]}</pre>",
        parse_mode="HTML",
        reply_markup=keyboards.template_detail_keyboard(name),
    )


@router.message(Command("new_template"))
async def cmd_new_template(msg: Message, state: FSMContext) -> None:
    await state.set_state(NewTemplateForm.name)
    await msg.answer(
        "📋 <b>New Template</b> - Step 1/3\n\nEnter the template <b>name</b>:",
        parse_mode="HTML",
        reply_markup=keyboards.cancel_keyboard(),
    )


@router.message(NewTemplateForm.name)
async def nt_name(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    name = msg.text.strip()
    existing = await db.fetchone("SELECT id FROM templates WHERE name = ?", (name,))
    if existing:
        await msg.answer(f"⚠️ Template '{name}' already exists. Choose a different name.")
        return
    await state.update_data(name=name)
    await msg.answer("📋 <b>New Template</b> - Step 2/3\n\nEnter a short <b>description</b>:",
                     parse_mode="HTML")
    await state.set_state(NewTemplateForm.description)


@router.message(NewTemplateForm.description)
async def nt_description(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    await state.update_data(description=msg.text.strip())
    await msg.answer(
        "📋 <b>New Template</b> - Step 3/3\n\n"
        "Enter the <b>system prompt</b> - the instruction that defines this agent's behaviour:",
        parse_mode="HTML",
    )
    await state.set_state(NewTemplateForm.system_prompt)


@router.message(NewTemplateForm.system_prompt)
async def nt_system_prompt(msg: Message, state: FSMContext) -> None:
    if not msg.text:
        return
    data = await state.get_data()
    await db.execute(
        "INSERT INTO templates (name, description, system_prompt, is_builtin) VALUES (?,?,?,0)",
        (data["name"], data.get("description", ""), msg.text.strip()),
    )
    await state.clear()
    await msg.answer(
        f"✅ <b>Template created!</b>\n\n"
        f"📋 <b>{data['name']}</b>\n"
        f"<i>{data.get('description','')}</i>\n\n"
        f"Use it with /new_agent.",
        parse_mode="HTML",
        reply_markup=keyboards.template_detail_keyboard(data["name"]),
    )
