import asyncio, pprint
from aiogoogle import Aiogoogle, HTTPError
import os
import json
import boto3
import aioboto3

PREFIX = '/telebot/'
ssm = boto3.client('ssm')
GOOGLE_API_KEY = ssm.get_parameter(Name=f'{PREFIX}GOOGLE_API_KEY')['Parameter']['Value']
SNS_ARN = os.getenv('TOPIC_ARN')


async def check_playlist(item, youtube, aiogoogle, sns):
    try:
        playlist_result = await aiogoogle.as_api_key(
            youtube.playlistItems.list(
                part=['id', 'contentDetails'],
                maxResults=50,
                playlistId=item['playlist_id']
            )
        )
        while playlist_result.get('nextPageToken', None):
            playlist_result = await aiogoogle.as_api_key(
                youtube.playlistItems.list(
                    part=['id', 'contentDetails'],
                    pageToken=playlist_result['nextPageToken'],
                    maxResults=50,
                    playlistId=item['playlist_id']
                )
            )
        if len(playlist_result['items'][-1]['contentDetails']):
            video_id = playlist_result['items'][-1]['contentDetails']['videoId']
            if video_id != item.get('last_video', ''):
                payload = json.dumps({
                    "chat_id": str(item['chat_id']),
                    "video_id": str(video_id)
                })
                await sns.publish(
                    TargetArn=SNS_ARN,
                    Message=json.dumps({'default': payload}),
                    MessageStructure='json'
                )

    except HTTPError:
        return


async def check_new_videos():
    session = aioboto3.Session()
    async with Aiogoogle(api_key=GOOGLE_API_KEY) as aiogoogle, \
            session.resource('dynamodb') as dynamodb, \
            session.client('sns') as sns:
        youtube = await aiogoogle.discover('youtube', 'v3')
        table = await dynamodb.Table('bot-base')

        result_set = await table.scan(
            FilterExpression='attribute_exists(playlist_id)'
        )
        tasks = [asyncio.ensure_future(
            check_playlist(item, youtube, aiogoogle, sns)
        ) for item in result_set['Items']]
        await asyncio.wait(tasks)


def lambda_handler(event, context):
    asyncio.run(check_new_videos())
