from flask import render_template, url_for, flash, redirect, request, abort, session
from imagebuilder import app, db, bcrypt,login_manager
from imagebuilder.forms import LoginForm,RegistrationForm,CopyPublicKey,AddTCForm
from flask_login import login_user, current_user, logout_user, login_required
from imagebuilder.models import User,Registered_TC
import subprocess
import time
import paramiko



#Set Paramiko Environment
global client
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.client.AutoAddPolicy)

#Home Page
@app.route('/',methods=['GET','POST'])
def home():
    return render_template('home.html',title='Home')


#Register ThinClient
@app.route('/register_tc',methods=['POST','GET'])
@login_required
def register_tc():
    page = request.args.get('page',1,type=int)
    regs_tc_count = db.session.query(Registered_TC).count()
    regs_tcs = Registered_TC.query.paginate(page=page,per_page=4)

    return render_template('register_tc.html',title='Register ThinClient',regs_tc_count=regs_tc_count,regs_tcs=regs_tcs)

#Add New TC
@app.route('/add_new_tc',methods=['POST','GET'])
@login_required
def add_new_tc():

    #Show Public Key
    with open('/root/.ssh/id_rsa.pub',"r") as f:
        publickey_content = f.read()

    form = CopyPublicKey()
    addtcform = AddTCForm()

    if form.validate_on_submit():
        cmd = "sshpass -p 'root123' ssh-copy-id -i ~/.ssh/id_rsa.pub -o StrictHostKeyChecking=no "+form.username.data
        proc = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        o,e = proc.communicate()
        if proc.returncode != 0:
            flash('Connection to ThinClient Timeout','danger')
            return redirect('add_new_tc')
        else:
            #Updating Database
            tc_ipaddress = form.username.data.split('@')[1]
            tc_username = form.username.data.split('@')[0]
            client.connect(tc_ipaddress,username=tc_username,timeout=3)
            stdin, stdout, stderr = client.exec_command("hostname")
            for line1 in stdout:
                print(line1)
            try:
                tc1 = Registered_TC(username=tc_username,ipaddress=tc_ipaddress,hostname=line1,register_tc_host=current_user)
                db.session.add(tc1)
                db.session.commit()
            except Exception as ee:
                flash(f"ThinClient is already Registered !",'info')
                return redirect(url_for('add_new_tc'))
                    
            flash('ThinClient Registered','success')
            return redirect('register_tc')

    if addtcform.validate_on_submit():
        try:
            remote_tc_ip = addtcform.remote_host_ip.data
            client.connect(remote_tc_ip,username=addtcform.tc_username.data,timeout=3)
            stdin, stdout, stderr = client.exec_command("hostname")
            
            for line2 in stdout:
                print(line2)
            try:
                tc2 = Registered_TC(username=addtcform.tc_username.data,ipaddress=remote_tc_ip,hostname=line2,register_tc_host=current_user)
                db.session.add(tc2)   
                db.session.commit()
            except Exception as ee:
                flash(f"ThinClient is already Registered !",'info')
                return redirect(url_for('add_new_tc'))

        except Exception as ee:
            flash(f"Connection to ThinClient Timeout",'danger')
            return redirect(url_for('add_new_tc'))

        flash('ThinClient Registered','success')   
        return redirect('register_tc') 

    return render_template('add_new_tc.html',title='Add New TC',publickey_content=publickey_content,form=form,addtcform=addtcform)


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