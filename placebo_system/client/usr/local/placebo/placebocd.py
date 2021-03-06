#!/usr/bin/env python

import sys, os, time, atexit, array, string
from signal import SIGTERM 
from socket import *
from threading import Thread
import subprocess

from placebo_client import *



class Daemon:
	def __init__(self, pidfile, stdin='/dev/null', stdout='/dev/null', stderr='/dev/null'):
		self.stdin = stdin
		self.stdout = stdout
		self.stderr = stderr
		self.pidfile = pidfile
	
	def daemonize(self):
		"""
		do the UNIX double-fork magic, see Stevens' "Advanced 
		Programming in the UNIX Environment" for details (ISBN 0201563177)
		http://www.erlenstar.demon.co.uk/unix/faq_2.html#SEC16
		"""
		try: 
			pid = os.fork() 
			if pid > 0:
				# exit first parent
				sys.exit(0) 
		except OSError, e: 
			sys.stderr.write("fork #1 failed: %d (%s)\n" % (e.errno, e.strerror))
			sys.exit(1)
	
		# decouple from parent environment
		os.chdir("/") 
		os.setsid() 
		os.umask(0) 
	
		# do second fork
		try: 
			pid = os.fork() 
			if pid > 0:
				# exit from second parent
				sys.exit(0) 
		except OSError, e: 
			sys.stderr.write("fork #2 failed: %d (%s)\n" % (e.errno, e.strerror))
			sys.exit(1) 
	
		# redirect standard file descriptors
		sys.stdout.flush()
		sys.stderr.flush()
		si = file(self.stdin, 'r')
		so = file(self.stdout, 'a+')
		se = file(self.stderr, 'a+', 0)
		os.dup2(si.fileno(), sys.stdin.fileno())
		os.dup2(so.fileno(), sys.stdout.fileno())
		os.dup2(se.fileno(), sys.stderr.fileno())
	
		# write pidfile
		atexit.register(self.delpid)
		pid = str(os.getpid())
		file(self.pidfile,'w+').write("%s\n" % pid)
	
	def delpid(self):
		os.remove(self.pidfile)

	def start(self):
		"""
		Start the daemon
		"""
		# Check for a pidfile to see if the daemon already runs
		try:
			pf = file(self.pidfile,'r')
			pid = int(pf.read().strip())
			pf.close()
		except IOError:
			pid = None
	
		if pid:
			message = "pidfile %s already exist. Daemon already running?\n"
			sys.stderr.write(message % self.pidfile)
			sys.exit(1)
		
		# Start the daemon
		self.daemonize()
		self.run()

	def stop(self):
		"""
		Stop the daemon
		"""
		# Get the pid from the pidfile
		try:
			pf = file(self.pidfile,'r')
			pid = int(pf.read().strip())
			pf.close()
		except IOError:
			pid = None
	
		if not pid:
			message = "pidfile %s does not exist. Daemon not running?\n"
			sys.stderr.write(message % self.pidfile)
			return # not an error in a restart

		# Try killing the daemon process	
		try:
			while 1:
				os.kill(pid, SIGTERM)
				time.sleep(0.1)
		except OSError, err:
			err = str(err)
			if err.find("No such process") > 0:
				if os.path.exists(self.pidfile):
					os.remove(self.pidfile)
			else:
				print str(err)
				sys.exit(1)

	def restart(self):
		"""
		Restart the daemon
		"""
		self.stop()
		self.start()

	def run(self):
		##### MAIN #####
		port=int(get_config_parameter("cln_port"))
		host=get_config_parameter("cln_addr")
		addr=(host,port)

		serversocket = socket(AF_INET, SOCK_STREAM)
		#serversocket.setsockopt(serversocket.SOL_SOCKET, serversocket.SO_KEEPALIVE,1)
		serversocket.setsockopt(SOL_SOCKET, SO_REUSEADDR, 1)
		serversocket.bind(addr)
		serversocket.listen(1)

		print "Placebo Client-Daemon started..."
		while 1: 
			try: 
				connection,address = serversocket.accept()
				if address[0] == get_config_parameter("adm_server") or gethostbyaddr(address[0])[0].split(".")[0] == get_config_parameter("adm_server"):
					new_thread = proc_server_request(connection)
					new_thread.start()
				else:
					send_end(connection,"CLNT_999")
					connection.close()
			except:
				print "Exit"
				serversocket.close()
				sys.exit(1)

		serversocket.close()
		sys.exit(0)

#####################################################################################
# Thread for processing Server requests
#####################################################################################
class proc_server_request(Thread):
        def __init__ (self, connect):
                Thread.__init__(self)
                self.connect = connect
                self.connect.settimeout(5)

        def run(self):
                connect = self.connect
                enc_msg = recv_end(connect)
		
		#Checks for encryption and executes non-encrypted commands
                if enc_msg.split("\n")[0] == "-----BEGIN PGP MESSAGE-----":
                        msg = decrypt(enc_msg)
                elif clean_string(enc_msg[:8]) == "CLNT_NEW":
                        added = add_public_key(enc_msg[8:])
			if added == 0 and is_registered() != 0:
                        	send_end(connect,encrypt("CLNT_NEW"+get_public_key()))
                        	ret = recv_end(connect)
				print decrypt(ret)
                        	if decrypt(ret)[:-4] == "SRV_0000":
                        	        print "OK"
                        	return 0
			else: #If Server already added this Client
                        	send_end(connect,encrypt("CLNT_115"))
                else:
                        print "Error"
                        sys.exit(1)

		#Encrypted commands
                if clean_string(msg[:8]) == "CLNT_SCN":
                        if len(process_exists("clamscan -i -r "+clean_string(msg[8:-4]))) == 0:
				msg = scan_file(clean_string(msg[8:-4]))
                                enc_msg = encrypt("CLNT_000"+msg)
                                connect.send(encrypt("CLNT_DTA"))
                        else:
                                enc_msg = encrypt("CLNT_100")
                        time.sleep(1)
			send_end(connect,enc_msg)
                elif clean_string(msg[:8]) == "CLNT_VSU":
                        if len(process_exists("update_clam_signatures.sh")) == 0:
                                enc_msg = encrypt("CLNT_000"+update_virus_signatures())
                                connect.send(encrypt("CLNT_DTA"))
                        else:
                                enc_msg=encrypt("CLNT_100")
			time.sleep(1)
			send_end(connect,enc_msg)

		elif clean_string(msg[:8]) == "CLNT_GET":
			if get_config_parameter(msg[8:-4]) != None:
				send_end(connect,encrypt(get_config_parameter(msg[8:-4])))
			else:
				send_end(connect,encrypt("CLNT_401"))

		elif clean_string(msg[:8]) == "CLNT_SET":
			parameter=msg[8:].split("=")[0]
			value=msg[8:].split("=",1)[1]
			value=value[:-4]
			if get_config_parameter(parameter) != None:
				if set_config_parameter(parameter, value) == 0:
                                	send_end(connect,encrypt("CLNT_000"))
				else:
                                	send_end(connect,encrypt("CLNT_402"))
			else:
				send_end(connect,encrypt("CLNT_401"))

		elif  clean_string(msg[:8]) == "CLNT_PIG":
			send_end(connect,encrypt("CLNT_POG"))			
                else:
                        send_end(connect,encrypt("CLNT_001"))
                connect.close()


daemon = Daemon("/var/run/placebocd.pid", "/dev/stdin", "/dev/stdout", "/var/log/placebo_client.log")
daemon.start()



