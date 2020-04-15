from flask import render_template, url_for, flash, redirect, request, abort, session
from imagebuilder import app, db, bcrypt,login_manager
from imagebuilder.forms import LoginForm,RegistrationForm,AddTCForm,NewImageForm
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
    
    form = AddTCForm()

    if form.validate_on_submit():
        try:
            remote_tc_ip = form.remote_host_ip.data
            client.connect(remote_tc_ip,username='root',timeout=3)
            stdin, stdout, stderr = client.exec_command("hostname")
            
            for line2 in stdout:
                print(line2)
            try:
                tc2 = Registered_TC(ipaddress=remote_tc_ip,hostname=line2,register_tc_host=current_user)
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

    return render_template('add_new_tc.html',title='Add New TC',publickey_content=publickey_content,form=form)

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
    os.makedirs(img_build_path+str(img_build_id)+'/gz_mount')


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
                    flash(f"Error while Extracting GZ image",'danger')
                    return redirect(url_for('home'))
                else:
                    print("Successfly Extracted GZ image")
                    print("Mounting GZ image")
                    gz_mount_cmd0 = "losetup -f"
                    proc = subprocess.Popen(gz_mount_cmd0,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    e,o = proc.communicate()
                    loopdevice = e.decode('utf-8').rstrip('\n')

                    gz_mount_cmd1 = "losetup "+loopdevice+' '+img_build_path+str(img_build_id)+'/gz/'+os.path.basename(form.url_gz_image.data)[:-3]
                    proc = subprocess.Popen(gz_mount_cmd1,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    o = proc.communicate()
                    if proc.returncode !=0:
                        flash(f'Error: {gz_mount_cmd1}','danger')
                        return redirect(url_for('home'))
                    else:
                        print(f'Success : {gz_mount_cmd1}')
                        gz_mount_cmd2 = "kpartx -av "+loopdevice
                        proc = subprocess.Popen(gz_mount_cmd2,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                        o = proc.communicate()
                        if proc.returncode !=0:
                            flash(f'Error : {gz_mount_cmd2}','danger')
                            return redirect(url_for('home'))
                        else:
                            print(f'Success : {gz_mount_cmd2}')
                            gz_mount_cmd3 = "vgchange -ay lvm-vxl"
                            proc = subprocess.Popen(gz_mount_cmd3,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            e,o = proc.communicate()
                            print(f'Success : {gz_mount_cmd3}')
                            gz_mount_cmd4 = "vgscan --mknodes"
                            proc = subprocess.Popen(gz_mount_cmd4,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            o = proc.communicate()
                            if proc.returncode !=0:

                                flash(f'Error : {gz_mount_cmd4}','danger')
                                return redirect(url_for('home'))
                            else:
                                print(f'Success : {gz_mount_cmd4}')
                                gz_mount_cmd5 = "mount /dev/lvm-vxl/sda2 "+img_build_path+str(img_build_id)+'/gz_mount/'
                                proc = subprocess.Popen(gz_mount_cmd5,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                o = proc.communicate()

                                if proc.returncode !=0:
                                    flash(f'Error : {gz_mount_cmd5}','danger')
                                else:
                                    print(f'Success : {gz_mount_cmd5}')

                                    #Start Copying Files
                                    #Create SoftLinks
                                    # client.connect(str(form.remote_tc_ip.data),username='root',timeout=3)
                                    # stdin, stdout, stderr = client.exec_command("cd /root ; ln -s /sda1/boot boot; ln -s /sda1/data/core core; ln -s /sda1/data/basic basic; ln -s /sda1/data/apps apps")
                                    # stdin, stdout, stderr = client.exec_command("cd /root ; python -m SimpleHTTPServer")
                                    # #Boot
                                    # #Remove Boot contents from GZ
                                    # print("Info : Removeing Boot Contents")
                                    # rm_boot_cmd = "rm -rf "+img_build_path+str(img_build_id)+'/gz_mount/boot'
                                    # proc = subprocess.Popen(rm_boot_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # print(f'Success : Remove Boot Contents from GZ')
                                    # #Wget Boot contents to GZ
                                    # print("Info : Downloading Boot Contents")
                                    # client.connect(str(form.remote_tc_ip.data),username='root',timeout=3)
                                    # wget_boot_cmd = "wget -P "+img_build_path+str(img_build_id)+"/gz_mount/ -r –level=0 -E –ignore-length -x -k -p -erobots=off -np -nH --reject='index.html*' -N http://"+str(form.remote_tc_ip.data)+":8000/boot/"
                                    # proc = subprocess.Popen(wget_boot_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # print(f'Success : Downloaded /sda1/boot contents')
                                    # stdin, stdout, stderr = client.exec_command("killall python")

                                    # #Core
                                    # #Remove Core contents from GZ
                                    # print("Info : Removeing Core contents")
                                    # rm_core_cmd = "rm -rf "+img_build_path+str(img_build_id)+'/gz_mount/data/core'
                                    # proc = subprocess.Popen(rm_core_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # #Wget Core contents to GZ
                                    # print("Info : Downloading Core Contents")
                                    # client.connect(str(form.remote_tc_ip.data),username='root',timeout=3)
                                    # wget_core_cmd = "wget -P "+img_build_path+str(img_build_id)+"/gz_mount/data/ -r –level=0 -E –ignore-length -x -k -p -erobots=off -np -nH --reject='index.html*' -N http://"+str(form.remote_tc_ip.data)+":8000/core/"
                                    # proc = subprocess.Popen(wget_core_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # print(f'Success : Downloaded /sda1/data/core contents')
                                    # stdin, stdout, stderr = client.exec_command("killall python")

                                    
                                    # #Basic
                                    # #Remove Basic contents from GZ
                                    # print("Info : Removeing Basic Contents")
                                    # rm_basic_cmd = "rm -rf "+img_build_path+str(img_build_id)+'/gz_mount/data/basic'
                                    # proc = subprocess.Popen(rm_basic_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # #Wget Basic contents to GZ
                                    # print("Info : Downloading Basic Contents")
                                    # client.connect(str(form.remote_tc_ip.data),username='root',timeout=3)
                                    # #stdin, stdout, stderr = client.exec_command("cd /sda1/data/basic/ ; python -m SimpleHTTPServer")
                                    # wget_basic_cmd = "wget -P "+img_build_path+str(img_build_id)+"/gz_mount/data/ -r –level=0 -E –ignore-length -x -k -p -erobots=off -np -nH --reject='index.html*' -N http://"+str(form.remote_tc_ip.data)+":8000/basic/"
                                    # proc = subprocess.Popen(wget_basic_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # print(f'Success : Downloaded /sda1/data/basic contents')
                                    # stdin, stdout, stderr = client.exec_command("killall python")

                                    # #Apps
                                    # #Remove Apps contents from GZ
                                    # print("Info : Removeing Apps Contents")
                                    # rm_apps_cmd = "rm -rf "+img_build_path+str(img_build_id)+'/gz_mount/data/apps'
                                    # proc = subprocess.Popen(rm_apps_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # #Wget Apps contents to GZ
                                    # print("Info : Downloading Apps Contents")
                                    # client.connect(str(form.remote_tc_ip.data),username='root',timeout=3)
                                    # #stdin, stdout, stderr = client.exec_command("cd /sda1/data/apps/ ; python -m SimpleHTTPServer")
                                    # wget_apps_cmd = "wget -P "+img_build_path+str(img_build_id)+"/gz_mount/data/ -r –level=0 -E –ignore-length -x -k -p -erobots=off -np -nH --reject='index.html*' -N http://"+str(form.remote_tc_ip.data)+":8000/apps"
                                    # proc = subprocess.Popen(wget_apps_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    # o,e = proc.communicate()
                                    # print(e)
                                    # print(f'Success : Downloaded /sda1/data/apps contents')
                                    # stdin, stdout, stderr = client.exec_command("killall python")

                                    #Chmod All the Folders
                                    print("Info : Changing Permission")
                                    perm_cmd1 = "chmod -R 755 "+img_build_path+str(img_build_id)+"/gz_mount/boot"
                                    perm_cmd2 = "chmod -R 755 "+img_build_path+str(img_build_id)+"/gz_mount/data/*"
                                    
                                    proc = subprocess.Popen(perm_cmd1,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    proc = subprocess.Popen(perm_cmd2,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    #Create GZ File again
                                    print("Info: Creating Final GZ File")
                                    create_gz_cmd1 = "cd "+img_build_path+str(img_build_id)
                                    proc = subprocess.Popen(create_gz_cmd1,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    create_gz_cmd2 = "umount "+img_build_path+str(img_build_id)+"/gz_mount"
                                    proc = subprocess.Popen(create_gz_cmd2,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    create_gz_cmd3 = "vgchange -an lvm-vxl"
                                    proc = subprocess.Popen(create_gz_cmd3,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    create_gz_cmd4 = "losetup -d "+loopdevice
                                    proc = subprocess.Popen(create_gz_cmd4,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    create_gz_cmd5 = "kpartx -dv "+loopdevice
                                    proc = subprocess.Popen(create_gz_cmd5,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    create_gz_cmd6 = "gzip "+img_build_path+str(img_build_id)+"/gz/"+os.path.basename(form.url_gz_image.data)[:-3]
                                    proc = subprocess.Popen(create_gz_cmd6,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()

                                    create_gz_cmd7 = "mv "+img_build_path+str(img_build_id)+"/gz/"+os.path.basename(form.url_gz_image.data)+" "+img_build_path+str(img_build_id)+"/gz/"+form.new_image_name.data+".gz"
                                    proc = subprocess.Popen(create_gz_cmd7,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    
                                    print("Success : Final GZ Created")


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