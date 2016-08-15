# Auto Provision of Droplets
# Written by John Flynn

# Script uses python_digitalocean library to connect to DigitalOcean to create a droplet
# Once droplet is created, fabric is used to accomplish first time admin tasks on the server, these include:
# 1) Run apt-get update and apt-get upgrade to get system up to date
# 2) Create a new user, and set the password
# 3) Copy local public key to server under new users home dir
# 4) Configure SSH to disallow root login, listen on user specified port, disable plaintext password logon.
# 5) Configure UFW to allow only connections to user specified ssh port
# 6) Configure automatic security updates
# 7) Maybe more in the future?

import sys, time
import digitalocean
from fabric.api import *
from fabric.contrib.files import sed
from fabric.contrib.files import append
import string
import random
from ConfigParser import SafeConfigParser

#Load config file
parser = SafeConfigParser()
parser.read('config.ini')

# Variables pulled from config file
doapi_key = parser.get('droplet_settings', 'doapi_key')
dropletname = parser.get('droplet_settings', 'dropletname')
dropletregion = parser.get('droplet_settings', 'dropletregion')
dropletimage = parser.get('droplet_settings', 'dropletimage')
dropletsize = parser.get('droplet_settings', 'dropletsize')
backups = parser.get('droplet_settings', 'backups')
boxusername = parser.get('machine_settings', 'boxusername')
ssh_port = parser.get('machine_settings', 'ssh_port')
ssh_pubkeyfile = parser.get('machine_settings', 'ssh_pubkeyfile')

def create_droplet(token, name, region, image, size, keys, backups):
    droplet = digitalocean.Droplet(token=token,
                                  name=name,
                                  region=region,
                                  image=image,
                                  size_slug=size,
                                  ssh_keys=keys,
                                  backups=backups)
    sys.stdout.write("Building droplet, please wait")
    droplet.create()

    actions = droplet.get_actions()
    for action in actions:
        action.load()
        while (action.status <> 'completed'):
            #Print status once droplet is up
            sys.stdout.write(".")
            sys.stdout.flush()
            action.load()
    droplet_data = droplet.load()
    print ""
    print "Droplet creation complete. IP Address: " + droplet_data.ip_address
    return droplet_data.ip_address

def genpasswd(pwdsize):
    chars = string.letters + string.digits
    password = ''.join((random.choice(chars)) for x in range(pwdsize))
    return password

def deploy(hoststring):
    def upgradesys():
        print "Running apt-get update and apt-get upgrade to update system..."
        run("apt-get update && apt-get upgrade -y")

    def usermanagement():
        global password
        password = genpasswd(20)
        print "Changing root password..."
        run('echo root:%s | chpasswd' % password)
        global userpassword
        userpassword = genpasswd(20)
        print "Creating admin user: " + boxusername
        run('adduser %s --disabled-password --gecos ""'% boxusername)
        run('adduser %s sudo' % boxusername)
        run('echo %s:%s | chpasswd' % (boxusername, userpassword))
        print "Adding " + ssh_pubkeyfile + " to " + boxusername
        with open (ssh_pubkeyfile, "r") as pubkey:
            sshpubkey=pubkey.read()
        run('mkdir /home/%(0)s/.ssh && chown -R %(0)s:%(0)s /home/%(0)s/.ssh && chmod 700 /home/%(0)s/.ssh' % {'0': boxusername})
        run('touch /home/%s/.ssh/authorized_keys && echo %s > /home/%s/.ssh/authorized_keys' % (boxusername, sshpubkey, boxusername))
        run('chown -R %(0)s:%(0)s /home/%(0)s/.ssh/authorized_keys && chmod 600 /home/%(0)s/.ssh/authorized_keys' % {'0': boxusername})

    def sshconfig():
        print "Disabling root login, disabling password authentication and changing listening port of OpenSSH Daemon..."
        sed('/etc/ssh/sshd_config', 'Port 22', 'Port ' + ssh_port)
        sed('/etc/ssh/sshd_config', '#PasswordAuthentication yes', 'PasswordAuthentication no')
        sed('/etc/ssh/sshd_config', 'PermitRootLogin yes', 'PermitRootLogin no')
        run('service ssh restart')

    def ufwconfig():
        print "Enabling UFW and adding exception for ssh port..."
        if ssh_port == None:
            run('ufw allow 22/tcp')
        else:
            run('ufw allow %s/tcp' % ssh_port)
        run('ufw --force enable')

    def unattendedupgrades():
        print 'Enabling unattended security updates...'
        run('apt-get -yq install unattended-upgrades')
        append('/etc/apt/apt.conf.d/10periodic', 'APT::Periodic::Unattended-Upgrade "1";')

    print "Sleeping for 30 seconds to wait for host to come online..."
    time.sleep(30)
    # List holding deploy function names, to disable a deployment step, simply remove its name from this list
    actions=[upgradesys, usermanagement, sshconfig, ufwconfig, unattendedupgrades]
    for action in actions:
        execute(action, hosts=[hoststring])

def genserverinfofile():
    print 'Writing droplet information to serverinfo.txt...'
    outputfile = open('serverinfo.txt', 'w')
    outputfile.write('IP: %s \n' % droplet_ip)
    outputfile.write('SSH Port: %s \n' % ssh_port)
    outputfile.write('root: %s \n' % password)
    outputfile.write('%s: %s \n' % (boxusername, userpassword))
    print 'Box setup complete, connect using: ssh -p ' + ssh_port + ' ' + boxusername + '@' + droplet_ip

def main():
    manager = digitalocean.Manager(token=doapi_key)
    #add all keys to root account during creation, root login will be disabled later
    keys = manager.get_all_sshkeys()
    #Create droplet
    global droplet_ip
    droplet_ip = create_droplet(doapi_key, dropletname, dropletregion, dropletimage, dropletsize, keys, backups)
    connstring = "root@" + droplet_ip
    #time to deploy!
    deploy(connstring)
    genserverinfofile()
