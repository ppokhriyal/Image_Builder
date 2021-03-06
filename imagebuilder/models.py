from datetime import datetime
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from imagebuilder import db, login_manager, app
from flask_login import UserMixin


@login_manager.user_loader
def load_user(user_id):
	return User.query.get(int(user_id))


class User(db.Model,UserMixin):
	id = db.Column(db.Integer,primary_key=True)
	username = db.Column(db.String(20),unique=True,nullable=False)
	email = db.Column(db.String(120),unique=True,nullable=False)
	password = db.Column(db.String(60),nullable=False)
	password_decrypted = db.Column(db.String(60),nullable=False)
	reg_tc = db.relationship('Registered_TC',backref='register_tc_host',lazy=True,cascade='all,delete-orphan')
	new_img_build = db.relationship('New_Image_Build',backref='newimage_author',lazy=True,cascade='all,delete-orphan')

	def __repr__(self):
		return f"User('{self.username}','{self.email}')"


class Registered_TC	(db.Model):
	id = db.Column(db.Integer,primary_key=True)
	ipaddress = db.Column(db.String(20),unique=True,nullable=False)
	hostname = db.Column(db.String(20),nullable=False)
	user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

	def __repr__(self):
		
		return f"{self.ipaddress}"

class New_Image_Build(db.Model):
	id = db.Column(db.Integer,primary_key=True)
	imggenid = db.Column(db.Integer,unique=True,nullable=False)
	new_img_name = db.Column(db.String(100),nullable=False)
	date_posted = db.Column(db.DateTime(),nullable=False,default=datetime.now)
	description = db.Column(db.Text,nullable=False)
	final_img_url = db.Column(db.String(100),nullable=False)
	user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

	def __repr__(self):
		return f"New_Image_Build('{self.imggenid}','{self.new_img_name}','{self.description}','{self.final_img_url}')"