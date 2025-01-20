import imaplib
import email
from email.header import decode_header
import os
from datetime import datetime, timedelta
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
import dateutil.parser

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
            genai.configure(api_key="AIzaSyCtPO6UqJPlJ-6BKT51A77WziDHgntVUTo") #self.config.get_secret('GEMINI_API_KEY'))
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
        - Event name: string
        - Participants: array of email addresses
        - Location: string
        - Dates and Time: array of objects with this format:
            [{{"date_time": "YYYY-MM-DD HH:mm", "duration_minutes": number}}]
            For example:
            [
                {{"date_time": "2025-01-25 09:30", "duration_minutes": 60}},
                {{"date_time": "2025-01-26 12:15", "duration_minutes": 45}}
            ]
        - Repeat frequency (if any): string or null
        - End date (if any): "YYYY-MM-DD" or null

        Parse all dates into standard format YYYY-MM-DD HH:mm.
        Convert all times to 24-hour format.
        Return only the JSON object with no additional text.
        
        Example output:
        {{
            "event_name": "Team Meeting",
            "participants": ["john@example.com", "mary@example.com"],
            "location": "Conference Room A",
            "dates_and_time": [
                {{"date_time": "2025-01-25 14:30", "duration_minutes": 60}}
            ],
            "repeat_frequency": "weekly",
            "end_date": "2025-02-25"
        }}

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

    def is_duplicate_event(self, event_info, conn):
        """Check if an event with same name and time already exists"""
        self.logger.info(f"Checking for duplicate event: {event_info.get('event_name')}")
        cursor = conn.cursor()
        
        try:
            cursor.execute('''
            SELECT COUNT(*) FROM events 
            WHERE event_name = ? 
            AND event_data LIKE ?
            ''', (
                event_info.get('event_name'),
                f"%{event_info.get('date_time', '')}%"
            ))
            
            count = cursor.fetchone()[0]
            is_duplicate = count > 0
            self.logger.info(f"Duplicate check result: {'Found duplicate' if is_duplicate else 'No duplicate found'}")
            return is_duplicate
            
        except Exception as e:
            self.logger.error(f"Error checking for duplicates: {str(e)}")
            return False

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

            # Check for duplicates before saving
            if self.is_duplicate_event(event_info, conn):
                self.logger.warning(f"Skipping duplicate event: {event_info.get('event_name')}")
                return False

            unique_id = str(uuid.uuid4())
            timestamp = datetime.now()

            cursor.execute('''
            INSERT INTO events (unique_id, email_address, event_name, timestamp, event_data)
            VALUES (?, ?, ?, ?, ?)
            ''', (unique_id, email_address, event_info.get('event_name'), timestamp, str(event_info)))

            conn.commit()
            self.logger.info(f"Successfully saved event {unique_id} to database")
            return True
            
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
            
            dates_and_time = event_info.get('dates_and_time', [])
            if not isinstance(dates_and_time, list):
                dates_and_time = [dates_and_time]
            
            for date_time_info in dates_and_time:
                event = CalendarEvent()
                event.add('summary', event_info.get('event_name', 'Untitled Event'))
                
                try:
                    # Parse the date_time string
                    start_time = datetime.strptime(date_time_info['date_time'], '%Y-%m-%d %H:%M')
                    duration = int(date_time_info.get('duration_minutes', 60))  # default 60 minutes
                    
                    # Convert to UTC
                    start_time = pytz.timezone('America/New_York').localize(start_time).astimezone(pytz.UTC)
                    end_time = start_time + timedelta(minutes=duration)
                    
                    event.add('dtstart', start_time)
                    event.add('dtend', end_time)
                    
                except (ValueError, TypeError) as e:
                    self.logger.error(f"Error parsing date_time: {str(e)}")
                    continue
                
                # Add location if available
                if event_info.get('location'):
                    event.add('location', event_info['location'])
                
                # Add description with all event details
                description = f"""Event created via email processing system
Location: {event_info.get('location', 'Not specified')}
Duration: {duration} minutes
Repeat: {event_info.get('repeat_frequency', 'None')}
End Date: {event_info.get('end_date', 'Not specified')}
"""
                event.add('description', description)
                
                # Add attendees
                for attendee in event_info.get('participants', []):
                    if '@' in attendee:  # Only add if it's an email address
                        event.add('attendee', f'mailto:{attendee}')
                
                # Add organizer
                event.add('organizer', f'mailto:{self.email_address}')
                
                # Add the event to the calendar
                cal.add_component(event)
            
            self.logger.info("Calendar invite(s) created successfully")
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
                
                # Save to database and only send invite if it's not a duplicate
                if self.save_to_database(self.email_address, event_info):
                    # Create and send calendar invite
                    try:
                        ics_data = self.create_calendar_invite(event_info)
                        self.send_calendar_invite(sender_email, event_info, ics_data)
                    except Exception as e:
                        self.logger.error(f"Failed to send calendar invite: {str(e)}")
                else:
                    self.logger.info("Skipping calendar invite for duplicate event")

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