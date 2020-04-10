from flask import render_template, url_for, flash, redirect, request, abort, session
from imagebuilder import app, db, bcrypt,login_manager
from imagebuilder.forms import LoginForm,RegistrationForm,CopyPublicKey,AddTCForm,NewImageForm
from flask_login import login_user, current_user, logout_user, login_required
from imagebuilder.models import User,Registered_TC
import subprocess
import time
import paramiko
import random
import os
import os.path
import shutil
from os import path
import pathlib
from pathlib import Path
import urllib3
import wget
import mimetypes
import asyncio
import concurrent.futures
import requests

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
    #Check the status of Registered TC
    tc_ip_status = []
    for i in db.session.query(Registered_TC).all():
        try:
            client.connect(str(i),username='root',timeout=2)
            stdin, stdout, stderr = client.exec_command("hostname")
            if stdout.channel.recv_exit_status() != 0:
                tc_ip_status.append('Down')
            else:
                tc_ip_status.append('Running')
        except Exception as e:
            tc_ip_status.append('Down')

    return render_template('register_tc.html',title='Register ThinClient',regs_tc_count=regs_tc_count,regs_tcs=regs_tcs,tc_ip_status=tc_ip_status)

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

#Global variable Functions for Image Build
def image_build_var():

    global img_build_id, img_build_path
    img_build_id = random.randint(1111,9999)
    img_build_path = '/var/www/html/Images/'

    #Check if Image Build area is empty and finish.true is not available
    if not len(os.listdir(img_build_path)) == 0:
        #Remove all the Folders which don't have finish.true files
        for f in os.listdir(img_build_path):
            file = pathlib.Path(img_build_path+f+"/"+"finish.true")
            if not file.exists():
                shutil.rmtree(img_build_path+f)
    #Make working area
    os.makedirs(img_build_path+str(img_build_id))
    os.makedirs(img_build_path+str(img_build_id)+'/gz')

#Download size
async def get_size(url):
    response = requests.head(url)
    size = int(response.headers['Content-Length'])
    return size

#Download Range
def download_range(url, start, end, output):
    headers = {'Range': f'bytes={start}-{end}'}
    response = requests.get(url, headers=headers)

    with open(output, 'wb') as f:
        for part in response.iter_content(1024):
            f.write(part)

async def download(executor, url, output, chunk_size=1000000):
    loop = asyncio.get_event_loop()

    file_size = await get_size(url)
    chunks = range(0, file_size, chunk_size)

    tasks = [
        loop.run_in_executor(
            executor,
            download_range,
            url,
            start,
            start + chunk_size - 1,
            f'{output}.part{i}',
        )
        for i, start in enumerate(chunks)
    ]

    await asyncio.wait(tasks)

    with open(output, 'wb') as o:
        for i in range(len(chunks)):
            chunk_path = f'{output}.part{i}'

            with open(chunk_path, 'rb') as s:
                o.write(s.read())

            os.remove(chunk_path)


#Add new Image
@app.route('/add_build_image',methods=['GET','POST'])
@login_required
def build_image():
    form = NewImageForm()
    image_build_var()

    if form.validate_on_submit():

        #Check if Remote TC is alive
        try:
            client.connect(str(form.remote_tc_ip.data),timeout=3)
        except Exception as e:
            flash(f"No Valid Connection Found !",'danger')
            return redirect(url_for('home'))

        #Check for valid url for gz image    
        try:
            read_url = form.url_gz_image.data
            check_url = requests.head(read_url)

            if check_url.status_code == 200:
                print('URL IS LIVE')
                #Now Check the URL file is of gz extention and gz application
                response = requests.head(form.url_gz_image.data)
                content_type = response.headers['content-type']

                #Download the GZ file
                DOWNLOAD_URL = form.url_gz_image.data
                GZ_PATH = img_build_path+str(img_build_id)+'/gz/'+os.path.basename(form.url_gz_image.data)

                executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(download(executor, DOWNLOAD_URL, GZ_PATH))
                finally:
                    loop.close()

                #Extract GZ file
                gunzip_cmd = "gunzip "+GZ_PATH
                proc = subprocess.Popen(gunzip_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                o = proc.communicate()
                if proc.returncode != 0:
                    print("Error While Extracting GZ image")
                else:
                    print("Successfly Extracted GZ image")
            else:
                flash(f'Invalid URL : {form.url_gz_image.data}','danger')
                return redirect(url_for('home'))
        except Exception as e:
            print(e)
            flash(f'Invalid URL : {form.url_gz_image.data}','danger')
            return redirect(url_for('home'))

    return render_template('build_image.html',title='Build New Image',form=form,img_build_id=img_build_id)

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