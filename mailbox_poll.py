#!/usr/bin/env python
# pylint: disable=W0613, C0116
# type: ignore[union-attr]

"""
Simple Bot to check out you email for new messages.
Press Ctrl-C on the command line to stop the bot.
"""

import logging
import imaplib
import email
import argparse

from functools import partial
from collections.abc import Callable
from imapclient import imap_utf7
from telegram import Update
from telegram.ext import Updater, CommandHandler, CallbackContext
from telegram.ext.filters import Filters

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)

logger = logging.getLogger(__name__)


class EmailFolderConverter(argparse.Action):
    def __init__(self, *args, **kwargs):
        super(EmailFolderConverter, self).__init__(*args, **kwargs)

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, imap_utf7.encode(values))


def arg_parser():
    parser = argparse.ArgumentParser(description='Redirects letters from your mailbox to the bot\'s telegram')
    parser.add_argument('-t', '--token', type=str, help='Input telegram bot token')
    parser.add_argument('-c', '--chat', type=int, help='Input private telegram chat_id')
    parser.add_argument('-m', '--mail', type=str, help='Input mailbox url')
    parser.add_argument('-l', '--login', type=str, help='Input mailbox login')
    parser.add_argument('-p', '--password', type=str, help='Input mailbox password')
    parser.add_argument('-f', '--folder', type=str, help='Input polling mailbox folder name, enter it in "quotes"',
                        action=EmailFolderConverter)
    return parser


def create_imap_connection(storage):
    mail = imaplib.IMAP4_SSL(storage['mail'])
    mail.login(storage['login'], storage['password'])
    return mail


def imap_trace(func, storage):
    def wrapper(*args, **kwargs):
        c = create_imap_connection(storage)
        try:
            func(c, storage, *args, **kwargs)
        finally:
            try:
                c.close()
            except:
                pass
            c.logout()
    return wrapper


def select_email_folder(mail, storage):
    """Get email folders and select the one you want"""
    result, folders = mail.list()
    enum_folders = {}
    if result == 'OK':
        for num, f in enumerate(folders, 1):
            l = f.decode().split(' "/" ')
            enum_folders[num] = l[1]
            print(str(num) + '. ' + imap_utf7.decode(f))
    storage['folder'] = enum_folders.get(int(input('Select number of folder:')), 'INBOX')


def scan_email(mail, storage, context):
    """Get and Send the email message."""
    job = context.job
    mail.select(storage['folder'])
    result, data = mail.search(None, '(UNSEEN)')
    if result == 'OK':
        ids = data[0].split()
        for id in ids:
            result, data = mail.fetch(id, "(RFC822)")
            email_message = {
                part.get_content_type(): part.get_payload()
                for part in email.message_from_bytes(data[0][1]).walk()
            }
            result = email_message["text/plain"]
            context.bot.send_message(job.context, text=result)
    else:
        context.bot.send_message(job.context, text=result)


def remove_job_if_exists(name, context):
    """Remove job with given name. Returns whether job was removed."""
    current_jobs = context.job_queue.get_jobs_by_name(name)
    if not current_jobs:
        return False
    for job in current_jobs:
        job.schedule_removal()
    return True


def start(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Hi! Use /set <seconds> to set a timer')


def set_timer(job: Callable, update: Update, context: CallbackContext) -> None:
    """Add a job to the queue."""
    chat_id = update.message.chat_id
    try:
        interval = int(context.args[0])
        if interval < 0:
            update.message.reply_text('Sorry we can not go back to future!')
            return

        job_removed = remove_job_if_exists(str(chat_id), context)
        context.job_queue.run_repeating(job, interval=interval, context=chat_id, name=str(chat_id))

        text = 'Timer successfully set!'
        if job_removed:
            text += ' Old one was removed.'
        update.message.reply_text(text)

    except (IndexError, ValueError):
        update.message.reply_text('Usage: /set <seconds>')


def unset(update: Update, context: CallbackContext) -> None:
    """Remove the job if the user changed their mind."""
    chat_id = update.message.chat_id
    job_removed = remove_job_if_exists(str(chat_id), context)
    text = 'Timer successfully cancelled!' if job_removed else 'You have no active timer.'
    update.message.reply_text(text)


def main():
    """Run bot."""

    parser = arg_parser()
    storage = vars(parser.parse_args())

    updater = Updater(storage['token'])
    dispatcher = updater.dispatcher

    if storage['folder'] is None:
        imap_trace(select_email_folder, storage)()
    logging.info('Cmd line args storage: {0}'.format(storage))

    ChatFilter = Filters.chat(storage['chat'])

    dispatcher.add_handler(CommandHandler("start", start, ChatFilter))
    dispatcher.add_handler(CommandHandler("help", start, ChatFilter))
    dispatcher.add_handler(CommandHandler("set", partial(set_timer, imap_trace(scan_email, storage)), ChatFilter))
    dispatcher.add_handler(CommandHandler("unset", unset, ChatFilter))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()