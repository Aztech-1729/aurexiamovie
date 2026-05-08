# premium.py - Premium Payment Bot

import asyncio
from datetime import datetime, timezone, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from config import (
    PREMIUM_BOT_TOKEN, 
    PREMIUM_BOT_USERNAME,
    ADMIN_IDS, 
    QR_IMAGE_URL, 
    UPI_ID, 
    PREMIUM_PLANS,
    MAIN_GROUP_ID
)

# In-memory storage for pending payments
pending_payments = {}  # user_id -> {"plan_type": str, "user_id": int}

# ── Handlers ──────────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    
    if not args:
        await update.message.reply_text(
            "👋 Welcome to Premium Payment Bot!\n\n"
            "This bot is used for processing premium plan payments.\n"
            "Please select a plan from the main bot to continue."
        )
        return
    
    # Parse plan and user_id from /start command
    # Format: /start planType_userId (e.g., /start silver_123456789)
    param = args[0]
    if "_" not in param:
        await update.message.reply_text("❌ Invalid start parameter.")
        return
    
    try:
        plan_type, sender_id = param.rsplit("_", 1)
        sender_id = int(sender_id)
    except:
        await update.message.reply_text("❌ Invalid start parameter.")
        return
    
    # Validate plan type
    if plan_type not in PREMIUM_PLANS:
        await update.message.reply_text("❌ Invalid plan type.")
        return
    
    plan = PREMIUM_PLANS[plan_type]
    username = update.effective_user.username or "N/A"
    
    # Show payment details
    payment_text = f"""📦 {plan['name']} {plan['emoji']}

👤 User: @{username}
🆔 User ID: {sender_id}

💰 Price: {plan['price']}
📅 Duration: {plan['days']} days

━━━━━━━━━━━━━━━
💳 Payment Details:
UPI ID: {UPI_ID}
━━━━━━━━━━━━━━━

📸 After payment, send screenshot here"""

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel")]
    ])
    
    # Send QR image if available
    if QR_IMAGE_URL and not QR_IMAGE_URL.startswith("https://example.com"):
        try:
            await update.message.reply_photo(
                photo=QR_IMAGE_URL,
                caption=payment_text,
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"[QR Error] {e}")
            await update.message.reply_text(
                payment_text,
                reply_markup=keyboard
            )
    else:
        await update.message.reply_text(
            payment_text,
            reply_markup=keyboard
        )
    
    # Store pending payment
    pending_payments[user_id] = {
        "plan_type": plan_type,
        "sender_id": sender_id
    }


async def handle_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    data = query.data
    
    if data == "cancel":
        if user_id in pending_payments:
            del pending_payments[user_id]
        try:
            await query.edit_message_text("❌ Payment cancelled.")
        except:
            pass


async def handle_screenshot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user has pending payment
    if user_id not in pending_payments:
        await update.message.reply_text(
            "❌ No pending payment found.\n\n"
            "Please select a plan from the main bot first."
        )
        return
    
    payment_info = pending_payments[user_id]
    plan_type = payment_info["plan_type"]
    sender_id = payment_info["sender_id"]
    plan = PREMIUM_PLANS.get(plan_type)
    
    username = update.effective_user.username or "N/A"
    first_name = update.effective_user.first_name or "N/A"
    
    # Forward screenshot to admins
    for admin_id in ADMIN_IDS:
        try:
            # Send payment details
            await context.bot.send_message(
                admin_id,
                f"""💰 Payment Received - {plan['name']} {plan['emoji']}

👤 User: @{username}
🆔 Name: {first_name}
🆔 User ID: {user_id}
💰 Amount: {plan['price']}
📅 Plan: {plan['days']} days
🔗 Main Bot User: {sender_id}

━━━━━━━━━━━━━━━
Screenshot:"""
            )
            
            # Forward the photo
            if update.message.photo:
                await context.bot.send_photo(
                    admin_id,
                    photo=update.message.photo[-1].file_id,
                )
            elif update.message.document:
                await context.bot.send_document(
                    admin_id,
                    document=update.message.document.file_id,
                )
            
            # Add approve/reject buttons
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Approve", callback_data=f"approve_{sender_id}_{plan_type}_{plan['days']}"),
                 InlineKeyboardButton("❌ Reject", callback_data=f"reject_{sender_id}_{user_id}")]
            ])
            await context.bot.send_message(
                admin_id,
                "👆 Verify payment and click:",
                reply_markup=keyboard
            )
        except Exception as e:
            print(f"[Admin Notify Error] {e}")
    
    # Confirm to user
    await update.message.reply_text(
        "✅ Screenshot sent to admins!\n\n"
        "⏰ You will be notified once verified."
    )
    
    # Clear pending payment
    del pending_payments[user_id]


async def handle_payment_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    
    # Check if admin
    if user_id not in ADMIN_IDS:
        await query.answer("❌ Unauthorized!", show_alert=True)
        return
    
    data = query.data
    
    if data.startswith("approve_"):
        parts = data.split("_")
        target_user_id = int(parts[1])
        plan_type = parts[2]
        days = int(parts[3])
        
        # Notify user
        try:
            await context.bot.send_message(
                target_user_id,
                f"🎉 Congratulations! Your {plan_type.upper()} plan has been activated!\n\n"
                f"📅 Valid for: {days} days\n\n"
                "Enjoy unlimited searches! 🚀"
            )
        except Exception as e:
            print(f"[Notify User Error] {e}")
        
        await query.edit_message_text(f"✅ Approved! {plan_type.upper()} granted to user {target_user_id}")
    
    elif data.startswith("reject_"):
        parts = data.split("_")
        target_user_id = int(parts[1])
        payer_id = int(parts[2])
        
        # Notify user
        try:
            await context.bot.send_message(
                payer_id,
                "❌ Payment rejected. Please contact admin for more info."
            )
        except:
            pass
        
        await query.edit_message_text(f"❌ Payment rejected for user {payer_id}")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("💎 Premium Bot starting...")
    
    app = ApplicationBuilder().token(PREMIUM_BOT_TOKEN).build()
    
    # Command handlers
    app.add_handler(CommandHandler("start", start_command))
    
    # Callback query handlers
    app.add_handler(CallbackQueryHandler(handle_buttons))
    app.add_handler(CallbackQueryHandler(handle_payment_approval, pattern="^(approve_|reject_)"))
    
    # Message handlers
    app.add_handler(MessageHandler(filters.PHOTO, handle_screenshot))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_screenshot))
    
    print("💎 Premium Bot running...")
    app.run_polling()