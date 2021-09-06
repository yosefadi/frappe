# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: MIT. See LICENSE

import os
import email
import unittest
from datetime import datetime, timedelta

from frappe.email.receive import InboundMail, SentEmailInInboxError, Email
from frappe.email.email_body import get_message_id
import frappe
from frappe.test_runner import make_test_records
from frappe.core.doctype.communication.email import make
from frappe.desk.form.load import get_attachments
from frappe.email.doctype.email_account.email_account import notify_unreplied

make_test_records("User")
make_test_records("Email Account")



class TestEmailAccount(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.db_set("enable_incoming", 1)
		email_account.db_set("enable_auto_reply", 1)

	@classmethod
	def tearDownClass(cls):
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.db_set("enable_incoming", 0)

	def setUp(self):
		frappe.flags.mute_emails = False
		frappe.flags.sent_mail = None
		frappe.db.delete("Email Queue")
		frappe.db.delete("Unhandled Email")

	def get_test_mail(self, fname):
		with open(os.path.join(os.path.dirname(__file__), "test_mails", fname), "r") as f:
			return f.read()

	def test_incoming(self):
		cleanup("test_sender@example.com")

		test_mails = [self.get_test_mail('incoming-1.raw')]

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		self.assertTrue("test_receiver@example.com" in comm.recipients)
		# check if todo is created
		self.assertTrue(frappe.db.get_value(comm.reference_doctype, comm.reference_name, "name"))

	def test_unread_notification(self):
		self.test_incoming()

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		comm.db_set("creation", datetime.now() - timedelta(seconds = 30 * 60))

		frappe.db.delete("Email Queue")
		notify_unreplied()
		self.assertTrue(frappe.db.get_value("Email Queue", {"reference_doctype": comm.reference_doctype,
			"reference_name": comm.reference_name, "status":"Not Sent"}))

	def test_incoming_with_attach(self):
		cleanup("test_sender@example.com")

		existing_file = frappe.get_doc({'doctype': 'File', 'file_name': 'erpnext-conf-14.png'})
		frappe.delete_doc("File", existing_file.name)

		with open(os.path.join(os.path.dirname(__file__), "test_mails", "incoming-2.raw"), "r") as testfile:
			test_mails = [testfile.read()]

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		self.assertTrue("test_receiver@example.com" in comm.recipients)

		# check attachment
		attachments = get_attachments(comm.doctype, comm.name)
		self.assertTrue("erpnext-conf-14.png" in [f.file_name for f in attachments])

		# cleanup
		existing_file = frappe.get_doc({'doctype': 'File', 'file_name': 'erpnext-conf-14.png'})
		frappe.delete_doc("File", existing_file.name)


	def test_incoming_attached_email_from_outlook_plain_text_only(self):
		cleanup("test_sender@example.com")

		with open(os.path.join(os.path.dirname(__file__), "test_mails", "incoming-3.raw"), "r") as f:
			test_mails = [f.read()]

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		self.assertTrue("From: &quot;Microsoft Outlook&quot; &lt;test_sender@example.com&gt;" in comm.content)
		self.assertTrue("This is an e-mail message sent automatically by Microsoft Outlook while" in comm.content)

	def test_incoming_attached_email_from_outlook_layers(self):
		cleanup("test_sender@example.com")

		with open(os.path.join(os.path.dirname(__file__), "test_mails", "incoming-4.raw"), "r") as f:
			test_mails = [f.read()]

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		self.assertTrue("From: &quot;Microsoft Outlook&quot; &lt;test_sender@example.com&gt;" in comm.content)
		self.assertTrue("This is an e-mail message sent automatically by Microsoft Outlook while" in comm.content)

	def test_outgoing(self):
		make(subject = "test-mail-000", content="test mail 000", recipients="test_receiver@example.com",
			send_email=True, sender="test_sender@example.com")

		mail = email.message_from_string(frappe.get_last_doc("Email Queue").message)
		self.assertTrue("test-mail-000" in mail.get("Subject"))

	def test_sendmail(self):
		frappe.sendmail(sender="test_sender@example.com", recipients="test_recipient@example.com",
			content="test mail 001", subject="test-mail-001", delayed=False)

		sent_mail = email.message_from_string(frappe.safe_decode(frappe.flags.sent_mail))
		self.assertTrue("test-mail-001" in sent_mail.get("Subject"))

	def test_print_format(self):
		make(sender="test_sender@example.com", recipients="test_recipient@example.com",
			content="test mail 001", subject="test-mail-002", doctype="Email Account",
			name="_Test Email Account 1", print_format="Standard", send_email=True)

		sent_mail = email.message_from_string(frappe.get_last_doc("Email Queue").message)
		self.assertTrue("test-mail-002" in sent_mail.get("Subject"))

	def test_threading(self):
		cleanup(["in", ['test_sender@example.com', 'test@example.com']])

		# send
		sent_name = make(subject = "Test", content="test content",
			recipients="test_receiver@example.com", sender="test@example.com",doctype="ToDo",name=frappe.get_last_doc("ToDo").name,
			send_email=True)["name"]

		sent_mail = email.message_from_string(frappe.get_last_doc("Email Queue").message)

		with open(os.path.join(os.path.dirname(__file__), "test_mails", "reply-1.raw"), "r") as f:
			raw = f.read()
			raw = raw.replace("<-- in-reply-to -->", sent_mail.get("Message-Id"))
			test_mails = [raw]

		# parse reply
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		sent = frappe.get_doc("Communication", sent_name)

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		self.assertEqual(comm.reference_doctype, sent.reference_doctype)
		self.assertEqual(comm.reference_name, sent.reference_name)

	def test_threading_by_subject(self):
		cleanup(["in", ['test_sender@example.com', 'test@example.com']])

		with open(os.path.join(os.path.dirname(__file__), "test_mails", "reply-2.raw"), "r") as f:
			test_mails = [f.read()]

		with open(os.path.join(os.path.dirname(__file__), "test_mails", "reply-3.raw"), "r") as f:
			test_mails.append(f.read())

		# parse reply
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm_list = frappe.get_all("Communication", filters={"sender":"test_sender@example.com"},
			fields=["name", "reference_doctype", "reference_name"])
		# both communications attached to the same reference
		self.assertEqual(comm_list[0].reference_doctype, comm_list[1].reference_doctype)
		self.assertEqual(comm_list[0].reference_name, comm_list[1].reference_name)

	def test_threading_by_message_id(self):
		cleanup()
		frappe.db.delete("Email Queue")

		# reference document for testing
		event = frappe.get_doc(dict(doctype='Event', subject='test-message')).insert()

		# send a mail against this
		frappe.sendmail(recipients='test@example.com', subject='test message for threading',
			message='testing', reference_doctype=event.doctype, reference_name=event.name)

		last_mail = frappe.get_doc('Email Queue', dict(reference_name=event.name))

		# get test mail with message-id as in-reply-to
		with open(os.path.join(os.path.dirname(__file__), "test_mails", "reply-4.raw"), "r") as f:
			test_mails = [f.read().replace('{{ message_id }}', last_mail.message_id)]

		# pull the mail
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm_list = frappe.get_all("Communication", filters={"sender":"test_sender@example.com"},
			fields=["name", "reference_doctype", "reference_name"])

		# check if threaded correctly
		self.assertEqual(comm_list[0].reference_doctype, event.doctype)
		self.assertEqual(comm_list[0].reference_name, event.name)

	def test_auto_reply(self):
		cleanup("test_sender@example.com")

		test_mails = [self.get_test_mail('incoming-1.raw')]

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.receive(test_mails=test_mails)

		comm = frappe.get_doc("Communication", {"sender": "test_sender@example.com"})
		self.assertTrue(frappe.db.get_value("Email Queue", {"reference_doctype": comm.reference_doctype,
			"reference_name": comm.reference_name}))

	def test_handle_bad_emails(self):
		mail_content = self.get_test_mail(fname="incoming-1.raw")
		message_id = Email(mail_content).mail.get('Message-ID')

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.handle_bad_emails(uid=-1, raw=mail_content, reason="Testing")
		self.assertTrue(frappe.db.get_value("Unhandled Email", {'message_id': message_id}))

class TestInboundMail(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.db_set("enable_incoming", 1)

	@classmethod
	def tearDownClass(cls):
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		email_account.db_set("enable_incoming", 0)

	def setUp(self):
		cleanup()
		frappe.db.delete("Email Queue")
		frappe.db.delete("ToDo")

	def get_test_mail(self, fname):
		with open(os.path.join(os.path.dirname(__file__), "test_mails", fname), "r") as f:
			return f.read()

	def new_doc(self, doctype, **data):
		doc = frappe.new_doc(doctype)
		for field, value in data.items():
			setattr(doc, field, value)
		doc.insert()
		return doc

	def new_communication(self, **kwargs):
		defaults = {
			'subject': "Test Subject"
		}
		d = {**defaults, **kwargs}
		return self.new_doc('Communication', **d)

	def new_email_queue(self, **kwargs):
		defaults = {
			'message_id': get_message_id().strip(" <>")
		}
		d = {**defaults, **kwargs}
		return self.new_doc('Email Queue', **d)

	def new_todo(self, **kwargs):
		defaults = {
			'description': "Description"
		}
		d = {**defaults, **kwargs}
		return self.new_doc('ToDo', **d)

	def test_self_sent_mail(self):
		"""Check that we raise SentEmailInInboxError if the inbound mail is self sent mail.
		"""
		mail_content = self.get_test_mail(fname="incoming-self-sent.raw")
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 1, 1)
		with self.assertRaises(SentEmailInInboxError):
			inbound_mail.process()

	def test_mail_exist_validation(self):
		"""Do not create communication record if the mail is already downloaded into the system.
		"""
		mail_content = self.get_test_mail(fname="incoming-1.raw")
		message_id = Email(mail_content).message_id
		# Create new communication record in DB
		communication = self.new_communication(message_id=message_id)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		new_communiction = inbound_mail.process()

		# Make sure that uid is changed to new uid
		self.assertEqual(new_communiction.uid, 12345)
		self.assertEqual(communication.name, new_communiction.name)

	def test_find_parent_email_queue(self):
		"""If the mail is reply to the already sent mail, there will be a email queue record.
		"""
		# Create email queue record
		queue_record = self.new_email_queue()

		mail_content = self.get_test_mail(fname="reply-4.raw").replace(
			"{{ message_id }}", queue_record.message_id
		)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		parent_queue = inbound_mail.parent_email_queue()
		self.assertEqual(queue_record.name, parent_queue.name)

	def test_find_parent_communication_through_queue(self):
		"""Find parent communication of an inbound mail.
		Cases where parent communication does exist:
		1. No parent communication is the mail is not a reply.

		Cases where parent communication does not exist:
		2. If mail is not a reply to system sent mail, then there can exist co
		"""
		# Create email queue record
		communication = self.new_communication()
		queue_record = self.new_email_queue(communication=communication.name)
		mail_content = self.get_test_mail(fname="reply-4.raw").replace(
			"{{ message_id }}", queue_record.message_id
		)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		parent_communication = inbound_mail.parent_communication()
		self.assertEqual(parent_communication.name, communication.name)

	def test_find_parent_communication_for_self_reply(self):
		"""If the inbound email is a reply but not reply to system sent mail.

		Ex: User replied to his/her mail.
		"""
		message_id = "new-message-id"
		mail_content = self.get_test_mail(fname="reply-4.raw").replace(
			"{{ message_id }}", message_id
		)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		parent_communication = inbound_mail.parent_communication()
		self.assertFalse(parent_communication)

		communication = self.new_communication(message_id=message_id)
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		parent_communication = inbound_mail.parent_communication()
		self.assertEqual(parent_communication.name, communication.name)

	def test_find_parent_communication_from_header(self):
		"""Incase of header contains parent communication name
		"""
		communication = self.new_communication()
		mail_content = self.get_test_mail(fname="reply-4.raw").replace(
			"{{ message_id }}", f"<{communication.name}@{frappe.local.site}>"
		)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		parent_communication = inbound_mail.parent_communication()
		self.assertEqual(parent_communication.name, communication.name)

	def test_reference_document(self):
		# Create email queue record
		todo = self.new_todo()
		# communication = self.new_communication(reference_doctype='ToDo', reference_name=todo.name)
		queue_record = self.new_email_queue(reference_doctype='ToDo', reference_name=todo.name)
		mail_content = self.get_test_mail(fname="reply-4.raw").replace(
			"{{ message_id }}", queue_record.message_id
		)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		reference_doc = inbound_mail.reference_document()
		self.assertEqual(todo.name, reference_doc.name)

	def test_reference_document_by_record_name_in_subject(self):
		# Create email queue record
		todo = self.new_todo()

		mail_content = self.get_test_mail(fname="incoming-subject-placeholder.raw").replace(
			"{{ subject }}", f"RE: (#{todo.name})"
		)

		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		reference_doc = inbound_mail.reference_document()
		self.assertEqual(todo.name, reference_doc.name)

	def test_reference_document_by_subject_match(self):
		subject = "New todo"
		todo = self.new_todo(sender='test_sender@example.com', description=subject)

		mail_content = self.get_test_mail(fname="incoming-subject-placeholder.raw").replace(
			"{{ subject }}", f"RE: {subject}"
		)
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		reference_doc = inbound_mail.reference_document()
		self.assertEqual(todo.name, reference_doc.name)

	def test_create_communication_from_mail(self):
		# Create email queue record
		mail_content = self.get_test_mail(fname="incoming-2.raw")
		email_account = frappe.get_doc("Email Account", "_Test Email Account 1")
		inbound_mail = InboundMail(mail_content, email_account, 12345, 1)
		communication = inbound_mail.process()
		self.assertTrue(communication.is_first)
		self.assertTrue(communication._attachments)

def cleanup(sender=None):
	filters = {}
	if sender:
		filters.update({"sender": sender})

	names = frappe.get_list("Communication", filters=filters, fields=["name"])
	for name in names:
		frappe.delete_doc_if_exists("Communication", name.name)
		frappe.delete_doc_if_exists("Communication Link", {"parent": name.name})
