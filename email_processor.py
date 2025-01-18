import imaplib
import email
from email.header import decode_header
import os
from datetime import datetime
import uuid
import google.generativeai as genai
import sqlite3
import json
from secure_config import SecureConfig
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from icalendar import Calendar, Event as CalendarEvent
import smtplib
import pytz

class EmailEventProcessor:
    def __init__(self):
        # Set up logging
        self.setup_logging()
        self.logger = logging.getLogger(__name__)
        self.logger.info("Initializing EmailEventProcessor")
        
        self.config = SecureConfig()
        self.email_address = "infinityknowledge42@gmail.com"
        self.email_password = "liao wibc fayh tupx"
        
        # Initialize Gemini
        try:
            genai.configure(api_key=self.config.get_secret('GEMINI_API_KEY'))
            self.model = genai.GenerativeModel("gemini-1.5-pro-latest") 
            self.logger.info("Successfully initialized Gemini model")
        except Exception as e:
            self.logger.error(f"Failed to initialize Gemini model: {str(e)}")
            raise

    @staticmethod
    def setup_logging():
        """Set up logging configuration"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('email_processor.log'),
                logging.StreamHandler()
            ]
        )

    def connect_to_gmail(self):
        self.logger.info("Connecting to Gmail...")
        try:
            mail = imaplib.IMAP4_SSL("imap.gmail.com")
            mail.login(self.email_address, self.email_password)
            self.logger.info("Successfully connected to Gmail")
            return mail
        except Exception as e:
            self.logger.error(f"Failed to connect to Gmail: {str(e)}")
            raise

    def extract_event_info(self, email_body):
        self.logger.info("Extracting event information from email")
        prompt = f"""Extract the following information from the email content and return it as valid JSON:
        - Event name
        - Participants (list)
        - Location
        - Dates and Time
        - Repeat frequency (if any)
        - End date (if any)
        
        Return only the JSON object with no additional text.
        
        Email content:
        {email_body}
        """
        
        self.logger.info(f"Sending prompt to Gemini: {prompt}")
        try:
            response = self.model.generate_content(prompt)
            self.logger.info(f"Raw response: {response}")
            
            # Extract JSON from markdown code blocks if present
            response_text = response.text
            if "```json" in response_text:
                # Extract content between ```json and ```
                json_str = response_text.split("```json")[1].split("```")[0].strip()
            else:
                json_str = response_text.strip()
                
            self.logger.info(f"Extracted JSON string: {json_str}")
            
            # Parse the JSON string
            result = json.loads(json_str)
            self.logger.info(f"Successfully extracted event info: {json.dumps(result, indent=2)}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error generating/parsing response: {str(e)}")
            return {
                "error": "Failed to parse event information",
                "event_name": "Unknown Event",
                "raw_response": response.text if 'response' in locals() else None
            }

    def save_to_database(self, email_address, event_info):
        self.logger.info("Saving event to database")
        conn = sqlite3.connect('events.db')
        cursor = conn.cursor()
        
        try:
            # Create table if it doesn't exist
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS events
            (unique_id TEXT PRIMARY KEY,
             email_address TEXT,
             event_name TEXT,
             timestamp DATETIME,
             event_data TEXT)
            ''')

            unique_id = str(uuid.uuid4())
            timestamp = datetime.now()
            self.logger.info(f"SQL executed: {cursor.execute('''INSERT INTO events (unique_id, email_address, event_name, timestamp, event_data) VALUES (?, ?, ?, ?, ?)''', (unique_id, email_address, event_info.get('event_name'), timestamp, str(event_info)))}")
            cursor.execute('''
            INSERT INTO events (unique_id, email_address, event_name, timestamp, event_data)
            VALUES (?, ?, ?, ?, ?)
            ''', (unique_id, email_address, event_info.get('event_name'), timestamp, str(event_info)))

            conn.commit()
            self.logger.info(f"Successfully saved event {unique_id} to database")
        except Exception as e:
            self.logger.error(f"Database error: {str(e)}")
            raise
        finally:
            conn.close()

    def create_calendar_invite(self, event_info):
        """Create an ICS file from event information"""
        self.logger.info(f"Creating calendar invite for event: {event_info.get('event_name')}")
        
        try:
            # Create calendar event
            cal = Calendar()
            cal.add('prodid', '-//InfinityKnowledge Calendar//infinityknowledge42@gmail.com//')
            cal.add('version', '2.0')
            
            event = CalendarEvent()
            event.add('summary', event_info.get('event_name', 'Untitled Event'))
            
            # Parse date and time
            try:
                start_time = datetime.fromisoformat(event_info.get('date_time', ''))
            except (ValueError, TypeError):
                self.logger.error("Invalid date format in event_info")
                start_time = datetime.now()
            
            event.add('dtstart', start_time)
            event.add('dtend', start_time + timedelta(hours=1))  # Default 1 hour duration
            
            # Add location if available
            if event_info.get('location'):
                event.add('location', event_info['location'])
            
            # Add description
            event.add('description', f"Event created via email processing system")
            
            # Add attendees
            for attendee in event_info.get('participants', []):
                event.add('attendee', f'mailto:{attendee}')
            
            # Add organizer
            event.add('organizer', f'mailto:{self.email_address}')
            
            # Add the event to the calendar
            cal.add_component(event)
            
            self.logger.info("Calendar invite created successfully")
            return cal.to_ical()
            
        except Exception as e:
            self.logger.error(f"Error creating calendar invite: {str(e)}")
            raise

    def send_calendar_invite(self, recipient_email, event_info, ics_data):
        """Send calendar invite via email"""
        self.logger.info(f"Sending calendar invite to {recipient_email}")
        
        try:
            msg = MIMEMultipart()
            msg['From'] = self.email_address
            msg['To'] = recipient_email
            msg['Subject'] = f"Calendar Invite: {event_info.get('event_name', 'New Event')}"
            
            # Add email body
            body = f"""
            You're invited to: {event_info.get('event_name', 'New Event')}
            
            When: {event_info.get('date_time', 'Time not specified')}
            Where: {event_info.get('location', 'Location not specified')}
            
            Participants: {', '.join(event_info.get('participants', []))}
            
            This is an automatically generated calendar invite.
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Attach the calendar invite
            ics_part = MIMEBase('text', 'calendar', method='REQUEST', charset='UTF-8')
            ics_part.set_payload(ics_data)
            encoders.encode_base64(ics_part)
            ics_part.add_header('Content-Type', 'text/calendar; method=REQUEST; charset=UTF-8')
            ics_part.add_header('Content-Disposition', 'attachment; filename="invite.ics"')
            msg.attach(ics_part)
            
            # Send the email
            with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
                server.login(self.email_address, self.email_password)
                server.send_message(msg)
                
            self.logger.info(f"Calendar invite sent successfully to {recipient_email}")
            
        except Exception as e:
            self.logger.error(f"Error sending calendar invite: {str(e)}")
            raise

    def process_emails(self):
        self.logger.info("Starting email processing")
        mail = self.connect_to_gmail()
        mail.select('inbox')

        try:
            # Search for emails with subject "create event" (case insensitive)
            self.logger.info("Searching for emails with subject 'create event'")
            _, messages = mail.search(None, 'SUBJECT "create event"')
            message_count = len(messages[0].split())
            self.logger.info(f"Found {message_count} matching emails")

            for msg_num in messages[0].split():
                self.logger.info(f"Processing email {msg_num}")
                _, msg_data = mail.fetch(msg_num, '(RFC822)')
                email_body = ''
                self.logger.debug(f"Message data: {msg_data}")   
                email_message = email.message_from_bytes(msg_data[0][1])
                self.logger.debug(f"Email message: {email_message}")
                # Get email body
                if email_message.is_multipart():
                    self.logger.info("Processing multipart email")
                    for part in email_message.walk():
                        if part.get_content_type() == "text/plain":
                            email_body = part.get_payload(decode=True).decode()
                            break
                else:
                    self.logger.info("Processing single part email")
                    email_body = email_message.get_payload(decode=True).decode()

                self.logger.info(f"Email body length: {len(email_body)} characters")
                self.logger.info(f"Email body: {email_body}")
                # Get sender's email
                sender_email = email.utils.parseaddr(email_message['From'])[1]
                self.logger.info(f"Processing email from: {sender_email}")
                
                # Extract event information using LLM
                event_info = self.extract_event_info(email_body)
                
                # Save to database
                self.save_to_database(self.email_address, event_info)
                
                # Create and send calendar invite
                try:
                    ics_data = self.create_calendar_invite(event_info)
                    self.send_calendar_invite(sender_email, event_info, ics_data)
                except Exception as e:
                    self.logger.error(f"Failed to send calendar invite: {str(e)}")

        except Exception as e:
            self.logger.error(f"Error processing emails: {str(e)}")
            raise
        finally:
            self.logger.info("Logging out from Gmail")
            mail.logout()

if __name__ == "__main__":
    try:
        processor = EmailEventProcessor()
        processor.process_emails()
    except Exception as e:
        logging.error(f"Application error: {str(e)}")
        raise 