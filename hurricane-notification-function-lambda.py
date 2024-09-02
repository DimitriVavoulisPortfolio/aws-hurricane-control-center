import sys
import os
import json

print("Python version:", sys.version)
print("Sys path:", sys.path)
print("Contents of /opt:", os.listdir('/opt'))
print("Contents of /opt/lib/python3.12/site-packages:", os.listdir('/opt/lib/python3.12/site-packages'))

# Add the layer path to sys.path
sys.path.append("/opt/lib/python3.12/site-packages")

print("Updated Sys path:", sys.path)

import boto3
import requests
from datetime import datetime
from bs4 import BeautifulSoup
import bs4

print("Requests version:", requests.__version__)
print("BeautifulSoup version:", bs4.__version__)

s3_client = boto3.client('s3')
dynamodb = boto3.resource('dynamodb')
hurricane_table = dynamodb.Table('UpcomingHurricanes')

def lambda_handler(event, context):
    # Always update the 7-day image first
    update_7day_image()
    
    url = "https://www.nhc.noaa.gov/text/MIATWDAT.shtml"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    content = soup.find('pre').text
    
    try:
        start = content.index("...SPECIAL FEATURES...")
        end = content.index("...TROPICAL WAVES...")
        relevant_section = content[start:end]
        
        locations = {
            "Puerto Rico": "PuertoRico-topic",
            "Florida": "Florida-topic"
        }
        
        notifications_sent = False
        summary = []
        for location, topic_name in locations.items():
            if location in relevant_section:
                sentences = relevant_section.split('.')
                for sentence in sentences:
                    if location in sentence:
                        days = analyze_sentence(sentence)
                        if days is not None:
                            send_notification(topic_name, f"WARNING: Potential storm approaching {location} in {days} days", location)
                            update_hurricane_arrival(location, days)
                            summary.append(f"{location}: {days} days till arrival")
                            notifications_sent = True
                            break
            else:
                # If location is not mentioned, update with no threat
                update_hurricane_arrival(location, None)
        
        # Update the summary JSON
        update_summary_json(summary)
        
        if notifications_sent:
            return {
                'statusCode': 200,
                'body': 'Function executed successfully. Special features found and analyzed. 7-day image updated. Hurricane arrivals updated. Summary JSON updated.'
            }
        else:
            return {
                'statusCode': 200,
                'body': 'Function executed successfully. No special features requiring notification. 7-day image updated. Hurricane arrivals updated. Summary JSON updated.'
            }
    
    except ValueError:
        print("No special features found in the current report.")
        update_summary_json([])  # Update with empty summary
        return {
            'statusCode': 200,
            'body': 'Function executed successfully. No special features found in the current report. 7-day image updated. Hurricane arrivals updated. Summary JSON updated.'
        }
    except Exception as e:
        print(f"An error occurred while processing special features: {str(e)}")
        return {
            'statusCode': 500,
            'body': f'An error occurred while processing special features: {str(e)}. 7-day image was updated. Hurricane arrivals and summary JSON may not have been fully updated.'
        }

def analyze_sentence(sentence):
    days_of_week = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
    today = datetime.now().weekday()
    mentioned_days = [days_of_week.index(day) for day in days_of_week if day in sentence.lower()]
    
    if mentioned_days:
        days_until = []
        for day in mentioned_days:
            diff = day - today
            if diff <= 0:  # If the day is today or in the past (next week)
                diff += 7
            days_until.append(diff)
        return min(days_until)
    return None

def send_notification(topic_name, message, location):
    sns = boto3.client('sns')
    account_id = boto3.client('sts').get_caller_identity().get('Account')
    topic_arn = f"arn:aws:sns:us-east-1:{account_id}:{topic_name}"
    
    full_message = f"{message}\n\nRelevant report excerpt:\n{get_relevant_excerpt(location)}"
    
    sns.publish(TopicArn=topic_arn, Message=full_message)

def get_relevant_excerpt(location):
    url = "https://www.nhc.noaa.gov/text/MIATWDAT.shtml"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    content = soup.find('pre').text
    start = content.index("...SPECIAL FEATURES...")
    end = content.index("...TROPICAL WAVES...")
    relevant_section = content[start:end]
    sentences = relevant_section.split('.')
    for sentence in sentences:
        if location in sentence:
            return sentence.strip()
    return "No specific details found."

def update_7day_image():
    url = "https://www.nhc.noaa.gov/gtwo.php?basin=atlc&fdays=7"
    bucket_name = 'www.hurricanecontrol.com'  # Your S3 bucket name
    image_key = 'two_atl_7d0.png'
    
    try:
        # Fetch the HTML content
        response = requests.get(url)
        response.raise_for_status()
        
        # Parse the HTML content
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Find all image tags
        img_tags = soup.find_all('img')
        
        # Look for the image with 'two_atl_7d0' in its source
        img_tag = next((img for img in img_tags if 'two_atl_7d0' in img.get('src', '')), None)
        
        if not img_tag:
            raise Exception("Image not found in the HTML content")
        
        image_url = "https://www.nhc.noaa.gov" + img_tag['src']
        
        # Download the image
        img_response = requests.get(image_url)
        img_response.raise_for_status()
        
        # Upload the image to S3
        s3_client.put_object(
            Bucket=bucket_name,
            Key=image_key,
            Body=img_response.content,
            ContentType='image/png'
        )
        
        print(f"Successfully updated 7-day image in S3 bucket: {bucket_name}/{image_key}")
    except Exception as e:
        print(f"Error updating 7-day image: {str(e)}")
        raise  # Re-raise the exception to ensure it's caught in the main handler

def update_hurricane_arrival(location, days):
    try:
        current_time = datetime.now().isoformat()

        # Always create a new entry
        hurricane_table.put_item(
            Item={
                'location': location,
                'timestamp': current_time,
                'days_to_arrival': days if days is not None else "No current threat",
            }
        )
        print(f"Created new hurricane arrival information for {location}")

    except Exception as e:
        print(f"Error updating hurricane arrival information: {str(e)}")
        # We're not re-raising this exception to avoid interrupting the main function flow

def update_summary_json(summary):
    bucket_name = 'www.hurricanecontrol.com'  # Your S3 bucket name
    summary_key = 'hurricane_summary.json'
    
    try:
        if summary:
            summary_message = "\n".join(summary)
        else:
            summary_message = "No hurricane or tropical storm detected to arrive to the tracked locations in the coming days"
        
        summary_dict = {"message": summary_message}
        summary_json = json.dumps(summary_dict)
        
        s3_client.put_object(
            Bucket=bucket_name,
            Key=summary_key,
            Body=summary_json,
            ContentType='application/json'
        )
        
        print(f"Successfully updated summary JSON in S3 bucket: {bucket_name}/{summary_key}")
    except Exception as e:
        print(f"Error updating summary JSON: {str(e)}")