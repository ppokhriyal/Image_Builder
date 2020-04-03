from flask import render_template, url_for, flash, redirect, request, abort, session
from imagebuilder import app, db, bcrypt,login_manager
from imagebuilder.forms import LoginForm,RegistrationForm,CopyPublicKey
from flask_login import login_user, current_user, logout_user, login_required
from imagebuilder.models import User
import subprocess
import time

#Home Page
@app.route('/',methods=['GET','POST'])
def home():
    return render_template('home.html',title='Home')


#Register ThinClient
@app.route('/register_tc',methods=['POST','GET'])
def register_tc():
    return render_template('register_tc.html',title='Register ThinClient')

#Add New TC
@app.route('/add_new_tc',methods=['POST','GET'])
def add_new_tc():

    #Show Public Key
    with open('/root/.ssh/id_rsa.pub',"r") as f:
        publickey_content = f.read()

    form = CopyPublicKey()
    if form.validate_on_submit():
        #time.sleep(5)
        cmd = "sshpass -p 'root123' ssh-copy-id -i ~/.ssh/id_rsa.pub -o StrictHostKeyChecking=no "+form.username.data
        proc = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        o,e = proc.communicate()
        print(e)
    return render_template('add_new_tc.html',title='Add New TC',publickey_content=publickey_content,form=form)


#Login Page
@app.route('/login',methods=['GET','POST'])
def login():
    form = LoginForm()

    if form.validate_on_submit():

        user = User.query.filter_by(email=form.email.data).first()

        if user and bcrypt.check_password_hash(user.password,form.password.data):

            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('home'))
        else:

            flash('Login Unsuccessful. Please check email or password','danger')

    return render_template('login.html',title='Login',form=form)


#Register Page
#Register Page
@app.route('/register',methods=['GET','POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    form = RegistrationForm()
    if form.validate_on_submit():
        hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
        user = User(username=form.username.data, email=form.email.data, password=hashed_password,password_decrypted=form.password.data)
        db.session.add(user)
        db.session.commit()
        flash(f'Your Account has been created! You are now able to login','success')
        return redirect(url_for('login'))
    return render_template('register.html',title='Register',form=form)



#Logout
@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('home'))