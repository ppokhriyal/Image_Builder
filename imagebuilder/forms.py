from flask_wtf import FlaskForm
from flask_mde import Mde, MdeField
from flask_wtf.file import FileField, FileAllowed
from flask_login import current_user
from wtforms import StringField, PasswordField, SubmitField, BooleanField, TextAreaField, SelectField
from wtforms.ext.sqlalchemy.fields import QuerySelectField
from wtforms.validators import DataRequired, Length, Email, EqualTo, ValidationError, InputRequired,IPAddress
from imagebuilder.models import User,Registered_TC


#Login Form
class LoginForm(FlaskForm):
	email = StringField('Email',validators=[DataRequired(),Email()])
	password = PasswordField('Password',validators=[DataRequired()])
	submit = SubmitField('Login')

#Registration Form
class RegistrationForm(FlaskForm):

	username = StringField('Username',validators=[DataRequired(),Length(min=2,max=20)])
	email = StringField('Email',validators=[DataRequired(),Email()])
	password = PasswordField('Password',validators=[DataRequired()])
	confirm_password = PasswordField('Confirm Password',validators=[DataRequired(),EqualTo('password')])
	submit = SubmitField('Sign Up')

	def validate_username(self,username):
		user = User.query.filter_by(username=username.data).first()
		if user:
			raise ValidationError('That username is taken. Please choose a diffrent one.')

	def validate_email(self,email):
		user = User.query.filter_by(email=email.data).first()
		check_email_valid = email.data
		if check_email_valid.split('@')[1] != "vxlsoftware.com":
			raise ValidationError('Please enter your valid vxlsoftware email id.')
		if user:
		   raise ValidationError('That email is taken. Please choose a diffrent one.')

#Add ThinClient
class AddTCForm(FlaskForm):
	tc_username = StringField('Username',validators=[DataRequired()])
	remote_host_ip = StringField('Remote TC IP Address',validators=[DataRequired(),IPAddress(message="Please Give Valid IP-Address")])
	submit = SubmitField('Register')

	def validate_ipaddress(self,remote_host_ip):
		ip = Registered_TC.query.filter_by(ipaddress=remote_host_ip.data).first()

		if ip:
			raise ValidationError('This IPAddress is already registered')

#Build New Image
class NewImageForm(FlaskForm):
	image_build_id = StringField('Image Build ID',render_kw={'readonly':True},validators=[DataRequired()])
	new_image_name = StringField('New Image Name',validators=[DataRequired()])
	image_description = TextAreaField('Description',validators=[DataRequired()])
	remote_tc_ip = QuerySelectField(query_factory=lambda:Registered_TC.query.all())
	url_gz_image = StringField('URL Gz Image',validators=[DataRequired()])
	submit = SubmitField('Build')