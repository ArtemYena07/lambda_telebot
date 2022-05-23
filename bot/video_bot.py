import asyncio
from aiogoogle import Aiogoogle, HTTPError
import logging
import urllib.parse as urlparse
import os
import json
import boto3
from aiogram import Bot, Dispatcher, types
from enum import Enum


class State(Enum):
    DEFAULT = 0
    YT_LINK = 1


# Logger initialization and logging level setting
log = logging.getLogger(__name__)
log.setLevel(os.environ.get('LOGGING_LEVEL', 'INFO').upper())
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('bot-base')

PREFIX = '/telebot/'
ssm = boto3.client('ssm')
BOT_KEY = ssm.get_parameter(Name=f'{PREFIX}BOT_KEY')['Parameter']['Value']
GOOGLE_API_KEY = ssm.get_parameter(Name=f'{PREFIX}GOOGLE_API_KEY')['Parameter']['Value']
bot = Bot(BOT_KEY)


# Handlers
async def help(message: types.Message):
    await bot.send_message(message.chat.id, 'Some helpful commands:\n' +
                           '/help - list of all comands\n' +
                           '/add_link - add link to your youtube playlist\n' +
                           '/delete_link - stop sendig videos form playlist\n' +
                           '/check_link - returns link to playlist')


async def start(message: types.Message):
    response = table.get_item(Key={'chat_id': message.chat.id})
    if not response.get('Item', None):
        table.put_item(Item={'chat_id': message.chat.id, 'chat_state': State.DEFAULT.value})
    await bot.send_message(message.chat.id, 'Hello, {}!'.format(message.from_user.first_name))
    await help(message)


async def check_link(message: types.Message):
    response = table.get_item(Key={'chat_id': message.chat.id})
    if not response['Item'].get('playlist_id', None):
        await bot.send_message(message.chat.id, 'You have not set up link')
    else:
        await bot.send_message(message.chat.id, f'https://youtube.com/playlist?list={response["Item"]["playlist_id"]}')


async def delete_link(message: types.Message):
    table.update_item(
        Key={'chat_id': message.chat.id},
        UpdateExpression='set chat_state = :n, playlist_id=:p, last_video=:s',
        ExpressionAttributeValues={
            ':n': State.DEFAULT.value,
            ':p': None,
            ':s': None
        },
        ReturnValues='UPDATED_NEW'
    )
    await bot.send_message(message.chat.id, 'Link was deleted')


async def connect_youtube(message: types.Message):
    table.update_item(
        Key={'chat_id': message.chat.id},
        UpdateExpression="set chat_state = :n",
        ExpressionAttributeValues={
            ':n': State.YT_LINK.value
        },
        ReturnValues="UPDATED_NEW"
    )
    await bot.send_message(message.chat.id, 'Provide link to your playlist. ' +
                           'It should be public and format is\n' +
                           '`https://youtube.com/playlist?list=<playlist_id>`')


async def check_last_video(playlist_id: str) -> str:
    async with Aiogoogle(api_key=GOOGLE_API_KEY) as aiogoogle:
        youtube = await aiogoogle.discover('youtube', 'v3')
        result = await aiogoogle.as_api_key(
            youtube.playlistItems.list(
                part=['id', 'contentDetails'],
                maxResults=50,
                playlistId=playlist_id
            )
        )
        while result.get('nextPageToken', None):
            result = await aiogoogle.as_api_key(
                youtube.playlistItems.list(
                    part=['id', 'contentDetails'],
                    pageToken=result['nextPageToken'],
                    maxResults=50,
                    playlistId=playlist_id
                )
            )
        if not len(result['items'][-1]['contentDetails']):
            return ''
        else:
            return result['items'][-1]['contentDetails']['videoId']


async def validate_yt_link(message: types.Message):
    if 'https://youtube.com/playlist' in message.text or 'https://www.youtube.com/playlist' in message.text:
        parsed_url = urlparse.urlparse(message.text)
        try:
            playlist_id = urlparse.parse_qs(parsed_url.query)['list'][0]
            last_video = await check_last_video(playlist_id)
        except KeyError:
            await bot.send_message(message.chat.id, 'Invalid Link, try more')
        except HTTPError:
            await bot.send_message(message.chat.id, 'No such playlist (or it\'s closed)')
        else:
            table.update_item(
                Key={'chat_id': message.chat.id},
                UpdateExpression='set chat_state = :n, playlist_id=:p, last_video=:s',
                ExpressionAttributeValues={
                    ':n': State.DEFAULT.value,
                    ':p': playlist_id,
                    ':s': last_video
                },
                ReturnValues='UPDATED_NEW'
            )
            await bot.send_message(message.chat.id, 'Link was successfuly added')
    else:
        await bot.send_message(message.chat.id, 'Invalid Link, try more')


async def process_message(message: types.Message):
    response = table.get_item(Key={'chat_id': message.chat.id})
    state_value = response['Item']['chat_state']
    if State(state_value) == State.YT_LINK:
        await validate_yt_link(message)


# AWS Lambda funcs
async def register_handlers(dp: Dispatcher):
    """Registration all handlers before processing update."""

    dp.register_message_handler(start, commands=['start'])
    dp.register_message_handler(help, commands=['help'])
    dp.register_message_handler(connect_youtube, commands=['add_link'])
    dp.register_message_handler(check_link, commands=['check_link'])
    dp.register_message_handler(delete_link, commands=['delete_link'])
    dp.register_message_handler(process_message)

    log.debug('Handlers are registered.')


async def process_event(event, dp: Dispatcher):
    """
    Converting an AWS Lambda event to an update and handling that
    update.
    """

    log.debug('Update: ' + str(event))

    Bot.set_current(dp.bot)
    update = types.Update.to_object(event)
    await dp.process_update(update)


async def main(event):
    """
    Asynchronous wrapper for initializing the bot and dispatcher,
    and launching subsequent functions.
    """

    # Bot and dispatcher initialization
    dp = Dispatcher(bot)

    await register_handlers(dp)
    await process_event(event, dp)

    return 'ok'


def lambda_handler(event, context):
    """AWS Lambda handler."""

    event_body = json.loads(event['body'])
    return asyncio.get_event_loop().run_until_complete(main(event_body))
