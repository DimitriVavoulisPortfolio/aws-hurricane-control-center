import json
import boto3
from botocore.exceptions import ClientError

dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HurricaneNotificationUsers')
sns = boto3.client('sns')
sts = boto3.client('sts')

def lambda_handler(event, context):
    print(f"Received event: {json.dumps(event)}")  # Log the entire event for debugging
    
    try:
        # Check if the event is coming directly from API Gateway
        if 'body' in event:
            if isinstance(event['body'], str):
                body = json.loads(event['body'])
            else:
                body = event['body']
        else:
            # If 'body' is not in event, assume the event itself is the body
            body = event
        
        print(f"Parsed body: {json.dumps(body)}")  # Log the parsed body
        
        if 'contact' not in body or 'location' not in body:
            raise ValueError("Missing required fields: contact and location")
        
        contact = body['contact']
        location = body['location']
        contact_type = 'email' if '@' in contact else 'phone'
        
        print(f"Processing registration for: {contact}, {location}")

        # Check if user already exists
        response = table.get_item(Key={'contact': contact})
        if 'Item' in response:
            print(f"User already registered: {contact}")
            return create_response(400, 'User already registered')

        # Store user in DynamoDB
        table.put_item(
            Item={
                'contact': contact,
                'location': location,
                'contact_type': contact_type
            }
        )
        print(f"User stored in DynamoDB: {contact}, {location}")

        # Prepare SNS topic subscription
        topic_name = f"{location.replace(' ', '')}-topic"
        account_id = sts.get_caller_identity()['Account']
        topic_arn = f"arn:aws:sns:us-east-1:{account_id}:{topic_name}"
        
        print(f"Attempting to subscribe {contact} to topic: {topic_arn}")
        
        # Subscribe user to SNS topic
        try:
            response = sns.subscribe(
                TopicArn=topic_arn,
                Protocol='email' if contact_type == 'email' else 'sms',
                Endpoint=contact
            )
            print(f"SNS subscription response: {response}")
        except ClientError as e:
            print(f"Error subscribing to SNS: {e}")
            return create_response(500, f"Error subscribing to notifications: {str(e)}")

        return create_response(200, 'Successfully registered for hurricane notifications')

    except json.JSONDecodeError as e:
        print(f"JSON Decode Error: {e}")
        return create_response(400, 'Invalid JSON in request body')
    except ValueError as e:
        print(f"Value Error: {e}")
        return create_response(400, str(e))
    except Exception as e:
        print(f"Unexpected Error: {e}")
        return create_response(500, f'An unexpected error occurred: {str(e)}')

def create_response(status_code, message):
    return {
        'statusCode': status_code,
        'body': json.dumps(message),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        }
    }