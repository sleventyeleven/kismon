#!/usr/bin/env python
"""
Copyright (c) 2010, Patrick Salecker
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

    * Redistributions of source code must retain the above copyright notice,
      this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright notice,
      this list of conditions and the following disclaimer in
      the documentation and/or other materials provided with the distribution.
    * Neither the name of the author nor the names of its
      contributors may be used to endorse or promote products derived
      from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS
BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
"""

from client import *
from gui import MainWindow, MapWindow, show_timestamp
from config import Config
from map import MapWidget
from networks import Networks

import os
import sys
import subprocess

import gtk
import gobject

def check_map_dependencies():
	try:
		import champlaingtk
		import champlain
		import champlainmemphis
	except:
		return sys.exc_info()[1]
	
	try:
		champlain.Marker().set_image(None)
	except TypeError:
		return "libchamplain older than 0.6.1"
	
	pipe = subprocess.Popen("pkg-config --exists --print-errors 'memphis-0.2 >= 0.2.3'",
		shell=True, stderr=subprocess.PIPE)
	memphis_check = pipe.stderr.read().strip()
	if memphis_check != '':
		return memphis_check

class Core:
	def __init__(self):
		user_dir = "%s%s.kismon%s" % (os.path.expanduser("~"), os.sep, os.sep)
		if not os.path.isdir(user_dir):
			print "Creating Kismon user directory %s" % user_dir
			os.mkdir(user_dir)
		config_file = "%skismon.conf" % user_dir
		self.config_handler = Config(config_file)
		self.config_handler.read()
		self.config = self.config_handler.config
		
		self.marker_text = """Encryption: %s
MAC: %s
Manuf: %s
Type: %s
Channel: %s
First seen: %s
Last seen: %s"""
		
		self.sources = {}
		self.crypt_cache = {}
		self.networks = Networks()
		
		self.init_client_thread()
		if self.config["kismet"]["connect"] is True:
			self.client_start()
		
		if "--disable-map" in sys.argv:
			self.map_error = "--disable-map used"
		else:
			self.map_error = check_map_dependencies()
		if self.map_error is not None:
			self.map_error =  "%s\nMap disabled" % self.map_error
			print self.map_error, "\n"
		
		self.init_map()
		
		self.main_window = MainWindow(self.config,
			self.client_start,
			self.client_stop,
			self.map_widget,
			self.networks)
		self.main_window.add_to_log_list("Kismon started")
		if self.map_error is not None:
			self.main_window.add_to_log_list(self.map_error)
		
		self.networks_file = "%snetworks.json" % user_dir
		if os.path.isfile(self.networks_file):
			self.networks.load(self.networks_file)
		
		self.main_window.crypt_cache = self.crypt_cache
		
		if os.path.isdir("/proc/acpi/battery/BAT0"):
			f = open("/proc/acpi/battery/BAT0/info")
			for line in f.readlines():
				if line.startswith("last full capacity:"):
					max = line.split(":")[1].strip()
					self.battery_max = int(max.split()[0])
					break
			self.update_battery_bar()
			gobject.timeout_add(30000, self.update_battery_bar)
		else:
			self.battery_max = None
		
		gobject.threads_init()
		gobject.timeout_add(500, self.queue_handler)
		gobject.timeout_add(300, self.queue_handler_networks)
		
	def init_map(self):
		if self.map_error is not None:
			self.map_widget = None
			self.map = None
		else:
			self.map_widget = MapWidget(self.config["map"])
			self.map = self.map_widget.map
			self.map.set_zoom(16)
		
	def init_client_thread(self):
		self.client_thread = ClientThread(self.config["kismet"]["server"])
		self.client_thread.client.set_capabilities(
			('status', 'source', 'info', 'gps', 'bssid', 'ssid'))
		if "--create-kismet-dump" in sys.argv:
			self.client_thread.client.enable_dump()
		
	def client_start(self):
		if self.client_thread.is_running is True:
			self.client_stop()
		self.init_client_thread()
		if "--load-kismet-dump" in sys.argv:
			self.client_thread.client.load_dump(sys.argv[2])
		self.client_thread.start()
		
	def client_stop(self):
		self.client_thread.stop()
		
	def queue_handler(self):
		if self.main_window.gtkwin is None:
			self.quit()
			
		if len(self.client_thread.client.error) > 0:
			for error in self.client_thread.client.error:
				self.main_window.add_to_log_list(error)
			self.client_thread.client.error = []
		
		#gps
		gps = None
		fix = None
		gps_queue = self.client_thread.get_queue("gps")
		while True:
			try:
				data = gps_queue.pop()
				if gps is None:
					gps = data
				if data["fix"] > 1:
					fix = (data["lat"], data["lon"])
					break
			except IndexError:
				break
		if gps is not None:
			self.main_window.update_gps_table(gps)
			if fix is not None and self.map_widget is not None:
				self.map.set_position(fix[0], fix[1])
		
		#status
		for data in self.client_thread.get_queue("status"):
			self.main_window.add_to_log_list(data["text"])
		
		#info
		info_queue = self.client_thread.get_queue("info")
		try:
			data = info_queue.pop()
			self.main_window.update_info_table(data)
		except IndexError:
			pass
			
		#source
		update = False
		for data in self.client_thread.get_queue("source"):
			self.sources[data["uuid"]] = data
			update = True
		if update is True:
			self.main_window.update_sources_table(self.sources)
		
		return True
		
	def queue_handler_networks(self):
		#ssid
		for data in self.client_thread.get_queue("ssid"):
			self.networks.add_ssid_data(data)
		
		#bssid
		bssids = {}
		for data in self.client_thread.get_queue("bssid"):
			mac = data["bssid"]
			self.networks.add_bssid_data(data)
			if mac in self.main_window.signal_graphs:
				self.main_window.signal_graphs[mac].add_value(data["signal_dbm"])
			
			bssids[mac] = True
		
		for mac in bssids:
			if self.map_widget is not None:
				self.add_network_to_map(mac)
		
		if self.map_widget is not None:
			self.map.marker_layer_add_new_markers()
		return True
		
	def quit(self):
		self.client_thread.stop()
		self.config_handler.write()
		self.networks.save(self.networks_file)
		
	def get_battery_capacity(self):
		filename = "/proc/acpi/battery/BAT0/state"
		if not os.path.isfile(filename):
			return False
		f = open(filename)
		for line in f.readlines():
			if line.startswith("remaining capacity:"):
				current = line.split(":")[1].strip()
				current = int(current.split()[0])
				return round(100.0 / self.battery_max * current, 1)
		return False
		
	def update_battery_bar(self):
		battery = self.get_battery_capacity()
		if battery is not False:
			self.main_window.set_battery_bar(battery)
		return True
		
	def add_network_to_map(self, mac):
		network = self.networks.get_network(mac)
		if network["type"] != "infrastructure":
			return
		
		try:
			crypt = self.crypt_cache[network["cryptset"]]
		except KeyError:
			crypt = decode_cryptset(network["cryptset"], True)
			self.crypt_cache[network["cryptset"]] = crypt
		
		if "WPA" in crypt:
			color = "red"
		elif "WEP" in crypt:
			color = "orange"
		else:
			color = "green"
		
		ssid = network["ssid"]
		if ssid == "":
			ssid = "<no ssid>"
		evils = (("&", "&amp;"),("<", "&lt;"),(">", "&gt;"))
		for evil, good in evils:
			ssid = ssid.replace(evil, good)
		
		time_format = "%d.%m.%Y %H:%M:%S"
		
		text = self.marker_text % (crypt, mac, network["manuf"],
			network["type"], network["channel"],
			time.strftime(time_format, time.localtime(network["firsttime"])),
			time.strftime(time_format, time.localtime(network["lasttime"]))
			)
		text = text.replace("&", "&amp;")
		
		self.map.add_marker(mac, ssid, text, color, network["lat"], network["lon"])
		
def main():
	core = Core()
	try:
		gtk.main()
	except KeyboardInterrupt:
		pass
	core.quit()

if __name__ == "__main__":
	main()
