from pytube import YouTube
from aiogram import Bot
from decimal import Decimal
import boto3
import asyncio
import os
import json

PREFIX = '/telebot/'
ssm = boto3.client('ssm')
BOT_KEY = ssm.get_parameter(Name=f'{PREFIX}BOT_KEY')['Parameter']['Value']


async def send_video(bot: Bot, chat_id: str, video_id: str, vide_name: str):
    await bot.send_video(chat_id, open(vide_name, 'rb'))
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table('bot-base')
    table.update_item(
        Key={'chat_id': Decimal(chat_id)},
        UpdateExpression='set last_video=:s',
        ExpressionAttributeValues={
            ':s': video_id
        },
        ReturnValues='UPDATED_NEW'
    )


def lambda_handler(event, context):
    message = json.loads(event['Records'][0]['Sns']['Message'])
    bot = Bot(BOT_KEY)
    chat_id = message['chat_id']
    video_id = message['video_id']
    yt = YouTube(f'https://www.youtube.com/watch?v={video_id}')
    yt = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
    yt.download('/tmp/')
    vide_name = '/tmp/' + next(filter(lambda el: '.mp4' in el, os.listdir('/tmp/')))
    asyncio.run(send_video(bot, chat_id, video_id, vide_name))
