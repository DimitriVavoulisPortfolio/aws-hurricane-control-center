import json
import boto3
import logging
from botocore.exceptions import ClientError

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS services
dynamodb = boto3.resource('dynamodb')
table = dynamodb.Table('HurricaneNotificationUsers')
sns = boto3.client('sns')
sts = boto3.client('sts')

def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")
    
    if event['httpMethod'] == 'POST':
        return handle_unsubscribe_request(event)
    else:
        return create_response(400, 'Unsupported HTTP method')

def handle_unsubscribe_request(event):
    try:
        body = json.loads(event['body'])
        contact = body['contact']
        
        # Check if user exists and get their details
        response = table.get_item(Key={'contact': contact})
        if 'Item' not in response:
            logger.warning(f"User not found: {contact}")
            return create_response(404, 'User not found')
        user = response['Item']
        
        # Determine contact type and location
        contact_type = 'email' if '@' in contact else 'phone'
        location = user.get('location', '').lower()
        
        # Determine the correct topic name
        if location == 'puerto rico':
            topic_name = 'PuertoRico-topic'
        elif location == 'florida':
            topic_name = 'Florida-topic'
        else:
            logger.error(f"Unknown location: {location}")
            return create_response(400, f'Unknown location: {location}')
        
        # Unsubscribe from SNS topic
        account_id = sts.get_caller_identity().get('Account')
        topic_arn = f"arn:aws:sns:us-east-1:{account_id}:{topic_name}"
        
        try:
            # List all subscriptions for the topic
            subscriptions = sns.list_subscriptions_by_topic(TopicArn=topic_arn)['Subscriptions']
            
            # Find the correct subscription and unsubscribe
            for sub in subscriptions:
                if contact_type == 'email' and sub['Protocol'] == 'email' and sub['Endpoint'] == contact:
                    sns.unsubscribe(SubscriptionArn=sub['SubscriptionArn'])
                    logger.info(f"Unsubscribed email {contact} from SNS topic {topic_name}")
                    break
                elif contact_type == 'phone':
                    # Remove any non-digit characters from both the contact and the endpoint
                    clean_contact = ''.join(filter(str.isdigit, contact))
                    clean_endpoint = ''.join(filter(str.isdigit, sub['Endpoint']))
                    if sub['Protocol'] == 'sms' and clean_endpoint == clean_contact:
                        sns.unsubscribe(SubscriptionArn=sub['SubscriptionArn'])
                        logger.info(f"Unsubscribed phone {contact} from SNS topic {topic_name}")
                        break
            else:
                logger.warning(f"No matching subscription found for {contact} in topic {topic_name}")
        except ClientError as e:
            logger.error(f"Error unsubscribing from SNS: {str(e)}")
            # Continue with deletion even if SNS unsubscribe fails
        
        # Remove user from DynamoDB
        table.delete_item(Key={'contact': contact})
        
        logger.info(f"User unsubscribed and removed: {contact}")
        return create_response(200, 'You have been successfully unsubscribed.')
    except KeyError as e:
        logger.error(f"KeyError: {str(e)}")
        return create_response(400, f'Missing required field: {str(e)}')
    except json.JSONDecodeError as e:
        logger.error(f"JSONDecodeError: {str(e)}")
        return create_response(400, 'Invalid JSON in request body')
    except ClientError as e:
        logger.error(f"AWS ClientError: {str(e)}")
        return create_response(500, f'An AWS service error occurred: {str(e)}')
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        return create_response(500, f'An unexpected error occurred: {str(e)}')

def create_response(status_code, message):
    return {
        'statusCode': status_code,
        'body': json.dumps({'message': message}),
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*'
        }
    }