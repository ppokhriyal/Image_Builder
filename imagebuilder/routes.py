from flask import render_template, url_for, flash, redirect, request, abort, session
from imagebuilder import app, db, bcrypt,login_manager
from imagebuilder.forms import LoginForm,RegistrationForm,AddTCForm,NewImageForm
from flask_login import login_user, current_user, logout_user, login_required
from imagebuilder.models import User,Registered_TC,New_Image_Build
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
import logging


#Set Paramiko Environment
global client
client = paramiko.SSHClient()
client.load_system_host_keys()
client.set_missing_host_key_policy(paramiko.client.AutoAddPolicy)

#Home Page
@app.route('/',methods=['GET','POST'])
def home():
    img_build_count = len(db.session.query(New_Image_Build).all())
    page = request.args.get('page',1,type=int)
    img = New_Image_Build.query.order_by(New_Image_Build.date_posted.desc()).paginate(page=page,per_page=4)
    return render_template('home.html',title='Home',img_build_count=img_build_count,img=img)


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
                cmd = "rm -Rf /var/www/html/Images/"+str(f)
                proc = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                o,e = proc.communicate()
                
    #Make working area
    os.makedirs(img_build_path+str(img_build_id))
    os.makedirs(img_build_path+str(img_build_id)+'/gz')
    os.makedirs(img_build_path+str(img_build_id)+'/alpine')
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
    global read_log

    #Start Logging
    with open('/var/www/html/log.txt',"w") as f:
        f.write("Building Image")
        f.write("\n")
        f.write("==============")
        f.write("\n")

    with open('/var/www/html/log.txt',"r") as f:
        read_log = f.read()

    if form.validate_on_submit():
        #Check if Remote TC is alive
        try:
            with open('/var/www/html/log.txt',"a") as f:
              f.write("INFO:[ Checking ThinClient Connectivity - "+str(form.remote_tc_ip.data)+" ]")
              f.write("\n")
            with open('/var/www/html/log.txt',"r") as f:
                read_log = f.read()

            client.connect(str(form.remote_tc_ip.data),timeout=3)
        except Exception as e:
            with open('/var/www/html/log.txt',"a") as f:
                f.write("ERROR:[ Connection Timeout - "+str(form.remote_tc_ip.data)+" ]")
                f.write("\n")
            with open('/var/www/html/log.txt',"r") as f:
                 read_log = f.read()

            flash(f"No Valid Connection Found !",'danger')
            #return redirect(url_for('home'))

        #ThinClient is Live
        with open('/var/www/html/log.txt',"a") as f:
                f.write("SUCCESS:[ Connection establish - "+str(form.remote_tc_ip.data)+" ]")
                f.write("\n")
        with open('/var/www/html/log.txt',"r") as f:
               read_log = f.read()

        #Check for valid url for gz image    
        try:
            with open('/var/www/html/log.txt',"a") as f:
              f.write("INFO:[ Checking GZ Image URL status - "+form.url_gz_image.data+" ]")
              f.write("\n")
            with open('/var/www/html/log.txt',"r") as f:
                read_log = f.read()

            read_url = form.url_gz_image.data
            check_url = requests.head(read_url)

            if check_url.status_code == 200:

                with open('/var/www/html/log.txt',"a") as f:
                    f.write("SUCCESS:[ "+form.url_gz_image.data+" ]")
                    f.write("\n")
                with open('/var/www/html/log.txt',"r") as f:
                    read_log = f.read()

                print('URL IS LIVE')
                #Now Check the URL file is of gz extention and gz application
                response = requests.head(form.url_gz_image.data)
                content_type = response.headers['content-type']

                #Download the GZ file
                with open('/var/www/html/log.txt',"a") as f:
                    f.write("INFO:[ Downloading GZ Image - "+form.url_gz_image.data+" ]")
                    f.write("\n")
                with open('/var/www/html/log.txt',"r") as f:
                    read_log = f.read()

                DOWNLOAD_URL = form.url_gz_image.data
                GZ_PATH = img_build_path+str(img_build_id)+'/gz/'+os.path.basename(form.url_gz_image.data)

                executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(download(executor, DOWNLOAD_URL, GZ_PATH))
                finally:
                    loop.close()

                with open('/var/www/html/log.txt',"a") as f:
                    f.write("SUCCESS:[ "+form.url_gz_image.data+" ]")
                    f.write("\n")
                with open('/var/www/html/log.txt',"r") as f:
                    read_log = f.read()

                #Extract GZ file
                with open('/var/www/html/log.txt',"a") as f:
                    f.write("INFO:[ Extracting GZ Image - "+os.path.basename(form.url_gz_image.data)+" ]")
                    f.write("\n")
                with open('/var/www/html/log.txt',"r") as f:
                    read_log = f.read()

                gunzip_cmd = "gunzip "+GZ_PATH
                proc = subprocess.Popen(gunzip_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                o = proc.communicate()
                if proc.returncode != 0:
                    with open('/var/www/html/log.txt',"a") as f:
                        f.write("ERROR:[ Extracting GZ Image - "+os.path.basename(form.url_gz_image.data)+" ]")
                        f.write("\n")
                    with open('/var/www/html/log.txt',"r") as f:
                        read_log = f.read()

                    flash(f"Error while Extracting GZ image",'danger')
                    #return redirect(url_for('home'))
                else:
                    with open('/var/www/html/log.txt',"a") as f:
                        f.write("SUCCESS:[ "+os.path.basename(form.url_gz_image.data)+" ]")
                        f.write("\n")
                    with open('/var/www/html/log.txt',"r") as f:
                        read_log = f.read()

                    print("Successfly Extracted GZ image")

                    #Mounting GZ Image
                    with open('/var/www/html/log.txt',"a") as f:
                        f.write("INFO:[ Mounting GZ Image - "+os.path.basename(form.url_gz_image.data)+" ]")
                        f.write("\n")
                    with open('/var/www/html/log.txt',"r") as f:
                        read_log = f.read()
                    
                    print("Mounting GZ image")

                    gz_mount_cmd0 = "losetup -f"
                    proc = subprocess.Popen(gz_mount_cmd0,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    e,o = proc.communicate()
                    loopdevice = e.decode('utf-8').rstrip('\n')

                    gz_mount_cmd1 = "losetup "+loopdevice+' '+img_build_path+str(img_build_id)+'/gz/'+os.path.basename(form.url_gz_image.data)[:-3]
                    proc = subprocess.Popen(gz_mount_cmd1,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                    o = proc.communicate()
                    if proc.returncode !=0:
                        with open('/var/www/html/log.txt',"a") as f:
                            f.write("ERROR:[ "+gz_mount_cmd1+" ]")
                            f.write("\n")
                        with open('/var/www/html/log.txt',"r") as f:
                            read_log = f.read()
                    
                        flash(f'Error: {gz_mount_cmd1}','danger')
                        #return redirect(url_for('home'))
                    else:
                        with open('/var/www/html/log.txt',"a") as f:
                            f.write("SUCCESS:[ "+gz_mount_cmd1+" ]")
                            f.write("\n")
                        with open('/var/www/html/log.txt',"r") as f:
                            read_log = f.read()
                        print(f'Success : {gz_mount_cmd1}')

                        gz_mount_cmd2 = "kpartx -av "+loopdevice
                        proc = subprocess.Popen(gz_mount_cmd2,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                        o = proc.communicate()
                        if proc.returncode !=0:
                            with open('/var/www/html/log.txt',"a") as f:
                                f.write("ERROR:[ "+gz_mount_cmd2+" ]")
                                f.write("\n")
                            with open('/var/www/html/log.txt',"r") as f:
                                read_log = f.read()
                    
                            flash(f'Error : {gz_mount_cmd2}','danger')
                            #return redirect(url_for('home'))
                        else:
                            with open('/var/www/html/log.txt',"a") as f:
                                f.write("SUCCESS:[ "+gz_mount_cmd2+" ]")
                                f.write("\n")
                            with open('/var/www/html/log.txt',"r") as f:
                                read_log = f.read()
                            print(f'Success : {gz_mount_cmd2}')

                            gz_mount_cmd3 = "vgchange -ay lvm-vxl"
                            proc = subprocess.Popen(gz_mount_cmd3,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            e,o = proc.communicate()

                            with open('/var/www/html/log.txt',"a") as f:
                                f.write("SUCCESS:[ "+gz_mount_cmd3+" ]")
                                f.write("\n")
                            with open('/var/www/html/log.txt',"r") as f:
                                read_log = f.read()
                            print(f'Success : {gz_mount_cmd3}')


                            gz_mount_cmd4 = "vgscan --mknodes"
                            proc = subprocess.Popen(gz_mount_cmd4,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            e,o = proc.communicate()

                            with open('/var/www/html/log.txt',"a") as f:
                                f.write("SUCCESS:[ "+gz_mount_cmd4+" ]")
                                f.write("\n")
                            with open('/var/www/html/log.txt',"r") as f:
                                read_log = f.read()
                            print(f'Success : {gz_mount_cmd4}')

                            gz_mount_cmd5 = "mount /dev/lvm-vxl/sda2 "+img_build_path+str(img_build_id)+'/gz_mount/'
                            proc = subprocess.Popen(gz_mount_cmd5,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                            e,o = proc.communicate()
                            if proc.returncode !=0:
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("ERROR:[ "+gz_mount_cmd5+" ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                flash(f'Error : {gz_mount_cmd5}','danger')
                                #return redirect(url_for('home'))
                            else:
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ "+gz_mount_cmd5+" ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()
                                print(f'Success : {gz_mount_cmd5}')

                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INFO:[ Downloading the boot,core,basic and apps content from ThinClient ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                #Start Copying Files
                                #Create SoftLinks
                                #client.connect(str(form.remote_tc_ip.data),username='root',timeout=3)
                                # stdin, stdout, stderr = client.exec_command("cd /root ; ln -s /sda1/boot boot; ln -s /sda1/data/core core; ln -s /sda1/data/basic basic; ln -s /sda1/data/apps apps")
                                # stdin, stdout, stderr = client.exec_command("cd /root ; python -m SimpleHTTPServer")

                                # #Boot
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INF:[ Downloading Boot Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()
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

                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ Downloaded Boot Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                # #Core
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INFO:[ Downloading Core Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

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

                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ Downloaded Core Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()
                                    
                                # #Basic
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INFO:[ Downloading Basic Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

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
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ Downloaded Basic Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                # #Apps
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INFO:[ Downloading Apps Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

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
                                
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ Downloaded Apps Contents ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                #Chmod All the Folders in GZ
                                perm_cmd1 = "chmod -R 755 "+img_build_path+str(img_build_id)+"/gz_mount/boot"
                                perm_cmd2 = "chmod -R 755 "+img_build_path+str(img_build_id)+"/gz_mount/data/*"
                                    
                                #Create GZ File again
                                create_gz_cmd1 = "cd "+img_build_path+str(img_build_id)
                                create_gz_cmd2 = "umount "+img_build_path+str(img_build_id)+"/gz_mount"

                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INFO:[ Creating Alpine CDF Files ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                #Create Alpine CDF
                                create_cdf_cmd1 = "partclone.vfat -c -s /dev/mapper/"+loopdevice.lstrip('/dev/')+"p1"+" -o "+img_build_path+str(img_build_id)+"/alpine/"+form.new_image_name.data.replace(' ','_')+"_part1.CDF"+" "+"-L "+img_build_path+str(img_build_id)+"/alpine/CDF1.log"
                                create_cdf_cmd2 = "partclone.ext4 -c -s /dev/mapper/lvm-* -o "+img_build_path+str(img_build_id)+"/alpine/"+form.new_image_name.data.replace(' ','_')+"_part2.CDF "+" "+"-L "+img_build_path+str(img_build_id)+"/alpine/CDF2.log"                              
                                create_cdf_cmd3 = "partclone.ext3 -c -s /dev/mapper/"+loopdevice.lstrip('/dev/')+"p3 -o "+img_build_path+str(img_build_id)+"/alpine/"+form.new_image_name.data.replace(' ','_')+"_part3.CDF "+" "+"-L "+img_build_path+str(img_build_id)+"/alpine/CDF3.log"

                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ "+create_cdf_cmd1+" ]")
                                    f.write("\n")
                                    f.write("SUCCESS:[ "+create_cdf_cmd2+" ]")
                                    f.write("\n")
                                    f.write("SUCCESS:[ "+create_cdf_cmd3+" ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()


                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("INFO:[ Creating Final GZ Image ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()    
                                    
                                #Create GZ File Continue
                                create_gz_cmd3 = "vgchange -an lvm-vxl"
                                create_gz_cmd4 = "losetup -d "+loopdevice                                
                                create_gz_cmd5 = "kpartx -dv "+loopdevice
                                create_gz_cmd6 = "gzip "+img_build_path+str(img_build_id)+"/gz/"+os.path.basename(form.url_gz_image.data)[:-3]
                                create_gz_cmd7 = "mv "+img_build_path+str(img_build_id)+"/gz/"+os.path.basename(form.url_gz_image.data)+" "+img_build_path+str(img_build_id)+"/gz/"+form.new_image_name.data.replace(' ','_')+".gz"
                                    
                                cmd_list = [perm_cmd1,perm_cmd2,create_gz_cmd1,
                                create_gz_cmd2,create_cdf_cmd1,create_cdf_cmd2,
                                create_cdf_cmd3,create_gz_cmd3,create_gz_cmd4,
                                create_gz_cmd5,create_gz_cmd6,create_gz_cmd7
                                ]

                                for cmdi in range(len(cmd_list)):
                                    proc = subprocess.Popen(cmd_list[cmdi],shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                    o,e = proc.communicate()
                                    print (f"Command Executed => {cmd_list[cmdi]}")
                                    print(f"Exit Code => {proc.returncode}")

                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ "+create_gz_cmd3+" ]")
                                    f.write("\n")
                                    f.write("SUCCESS:[ "+create_gz_cmd4+" ]")
                                    f.write("\n")
                                    f.write("SUCCESS:[ "+create_gz_cmd5+" ]")
                                    f.write("\n")
                                    f.write("SUCCESS:[ "+create_gz_cmd6+" ]")
                                    f.write("\n")
                                    f.write("SUCCESS:[ "+create_gz_cmd7+" ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()
                                        
                                #Writing MD5SUM
                                md5sum_gz_cmd = "md5sum "+img_build_path+str(img_build_id)+"/gz/*.gz"
                                proc = subprocess.Popen(md5sum_gz_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                o,e = proc.communicate()

                                with open(img_build_path+str(img_build_id)+"/gz/MD5SUM","w") as f:
                                    f.write(o.decode('utf-8').split(' ')[0])
                                    f.write("\n")

                                md5sum_cdf_cmd = "md5sum "+img_build_path+str(img_build_id)+"/alpine/*.CDF"
                                proc = subprocess.Popen(md5sum_cdf_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                o,e = proc.communicate()

                                for i in range(len(o.decode('utf-8').split('\n'))):
                                    with open(img_build_path+str(img_build_id)+"/alpine/MD5SUM","a") as f:
                                        print(o.decode('utf-8').split('\n')[i])
                                        f.write(o.decode('utf-8').split('\n')[i])
                                        f.write("\n")


                                #Update DataBase
                                print('Info : Updating DataBase')
                                update_database = New_Image_Build(imggenid=img_build_id,new_img_name=form.new_image_name.data.replace(' ','_'),description=form.image_description.data,final_img_url="http://"+img_build_path+str(img_build_id),newimage_author=current_user)
                                db.session.add(update_database)
                                db.session.commit()
                                print('Success: DataBase Updated')
                                
                                #Finish
                                Path(img_build_path+str(img_build_id)+"/"+"finish.true").touch()
                                
                                #Return to Home
                                with open('/var/www/html/log.txt',"a") as f:
                                    f.write("SUCCESS:[ Final Image ]")
                                    f.write("\n")
                                with open('/var/www/html/log.txt',"r") as f:
                                    read_log = f.read()

                                log_cmd = "mv /var/www/html/log.txt "+img_build_path+str(img_build_id)+'/'
                                proc = subprocess.Popen(log_cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                                o,e = proc.communicate()

                                flash(f'Image Build Successfull','success')
                                return redirect(url_for('home'))

            else:
                with open('/var/www/html/log.txt',"a") as f:
                    f.write("ERROR:[ "+form.url_gz_image.data+" ]")
                    f.write("\n")
                with open('/var/www/html/log.txt',"r") as f:
                    read_log = f.read()

                flash(f'Invalid URL : {form.url_gz_image.data}','danger')
                #return redirect(url_for('home'))
        except Exception as e:
            print(e)
            with open('/var/www/html/log.txt',"a") as f:
                f.write("ERROR:[ "+form.url_gz_image.data+" ]")
                f.write("\n")
            with open('/var/www/html/log.txt',"r") as f:
                read_log = f.read()
                
            flash(f'Invalid URL : {form.url_gz_image.data}','danger')
            #return redirect(url_for('home'))

    return render_template('build_image.html',title='Build New Image',form=form,img_build_id=img_build_id,read_log=read_log)
    


#View Details
@app.route('/view_img_details/<int:img_id>')
def img_details(img_id):
    img = New_Image_Build.query.get_or_404(img_id)
    
    #Read Md5sum of GZ image
    with open('/var/www/html/Images/'+str(img.imggenid)+"/gz/MD5SUM","r") as f:
        gz_md5sum = f.readline()

    #Read Image Build Logs
    with open('/var/www/html/Images/'+str(img.imggenid)+'/log.txt',"r") as f :
        view_log = f.read()

    #Read Md5sums of Alpine CDF Files
    alpine_cdf_list = []
    with open('/var/www/html/Images/'+str(img.imggenid)+"/alpine/MD5SUM","r") as f:
        for i in f:
            if i != '\n':
                alpine_cdf_list.append(i)

    return render_template('view.html',title='View',img=img,gz_md5sum=gz_md5sum,alpine_cdf_list=alpine_cdf_list,view_log=view_log)

#Delete Image
@app.route('/delete_image_data/<int:img_id>')
@login_required
def delete_img(img_id):
    img = New_Image_Build.query.get_or_404(img_id)
    if img.newimage_author != current_user:
        abort(403)
    db.session.delete(img)
    db.session.commit()

    cmd = "rm -rf  /var/www/html/Images/"+str(img.imggenid)
    proc = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    o,e = proc.communicate()
    flash('Your Image data has been deleted!','success')
    return redirect(url_for('home'))

#Cancel Build
@app.route('/cancel_build')
@login_required
def cancel_build():

    if not len(os.listdir('/var/www/html/Images/')) == 0:
        for f in os.listdir('/var/www/html/Images/'):
            file = pathlib.Path('/var/www/html/Images/'+f+'/finish.true')
            if not file.exists():
                cmd = "rm -Rf /var/www/html/Images/"+str(f)
                proc = subprocess.Popen(cmd,shell=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
                o,e = proc.communicate()

                flash(f'Your Image Build is canceled','info')
                return redirect(url_for('home'))

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