#!/usr/bin/env python3
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
from gi.repository import Gtk
from gi.repository import Gdk, GdkPixbuf
from gi.repository import GObject
from gi.repository import OsmGpsMap
import cairo
import io

import os
import hashlib

class Map:
	def __init__(self, config):
		self.config = config
		self.generator_is_running = False
		self.toggle_moving_button = None
		self.markers = {}
		self.networks_label_count = 0
		self.coordinates = {}
		
		self.init_osm()
		
		if os.path.isdir("/usr/share/kismon"):
			self.share_folder = "/usr/share/kismon/"
		else:
			dir = os.path.realpath(__file__).rsplit("/", 2)[0]
			self.share_folder = "%s%sfiles%s" % (dir, os.sep, os.sep)
		self.images = {
			"position": "%sposition.png" % self.share_folder
			}
		self.textures = {}
		self.create_dots()
		self.apply_config()
		
	def init_osm(self):
		if self.config["source"] != "custom":
			self.osm = OsmGpsMap.Map()
		else:
			self.osm = OsmGpsMap.Map(repo_uri=self.config["custom_source_url"],
				min_zoom=self.config["custom_source_min"],
				max_zoom=self.config["custom_source_max"])
		
		self.osd = OsmGpsMap.MapOsd(show_zoom=True, show_coordinates=False, show_scale=False, show_dpad=True, show_gps_in_dpad=True)
		self.osm.layer_add(self.osd)
		
		self.osm.connect('button-press-event', self.on_map_pressed)
		self.osm.set_keyboard_shortcut(OsmGpsMap.MapKey_t.UP, Gdk.keyval_from_name("Up"))
		self.osm.set_keyboard_shortcut(OsmGpsMap.MapKey_t.DOWN, Gdk.keyval_from_name("Down"))
		self.osm.set_keyboard_shortcut(OsmGpsMap.MapKey_t.LEFT, Gdk.keyval_from_name("Left"))
		self.osm.set_keyboard_shortcut(OsmGpsMap.MapKey_t.RIGHT, Gdk.keyval_from_name("Right"))
		self.osm.set_keyboard_shortcut(OsmGpsMap.MapKey_t.ZOOMIN, Gdk.keyval_from_name("Page_Up"))
		self.osm.set_keyboard_shortcut(OsmGpsMap.MapKey_t.ZOOMOUT, Gdk.keyval_from_name("Page_Down"))
		
		self.coordinates = {}
		for mac in list(self.markers.keys()):
			marker = self.markers[mac]
			del self.markers[mac]
			self.add_marker(marker.key, marker.color, marker.lat, marker.lon)
		
		self.widget = self.osm
		
	def apply_config(self):
		pass
		
	def create_dots(self):
		for color in ("red", "orange", "green", "crosshair"):
			if color == "crosshair":
				size = 32
			else:
				size = 16
			drawable = cairo.ImageSurface(cairo.FORMAT_RGB24, size, size)
			ctx = cairo.Context(drawable)
			ctx.set_source_rgba(1, 1, 1, 1)
			ctx.rectangle(0, 0, size, size)
			ctx.fill()
			ctx.stroke()
			
			if color == "red":
				ctx.set_source_rgb(1, 0, 0)
			elif color == "orange":
				ctx.set_source_rgb(1, 1, 0)
			elif color == "crosshair":
				ctx.set_source_rgb(0, 0, 0)
			else:
				ctx.set_source_rgb(0, 1, 0)
			
			if color == "crosshair":
				ctx.set_line_width(2)
				ctx.arc(size/2, size/2, size/4, 0, 3.14*2)
				ctx.move_to(3, size/2)
				ctx.line_to(size-3, size/2)
				ctx.move_to(size/2, 3)
				ctx.line_to(size/2, size-3)
			else:
				ctx.arc(size/2, size/2, size/2-1, 0, 3.14*2)
				ctx.fill()
			ctx.stroke()
			
			buffer = io.BytesIO()
			drawable.write_to_png(buffer)
			loader = GdkPixbuf.PixbufLoader.new_with_type('png')
			loader.write(buffer.getvalue())
			buffer.close()
			pixbuf = loader.get_pixbuf()
			loader.close()
			self.textures[color] = pixbuf.add_alpha(True , 255, 255, 255)
		
	def set_zoom(self, zoom):
		self.osm.set_zoom(zoom)
		
	def zoom_in(self, actor=None, event=None, view=None):
		self.osm.zoom_in()
		
	def zoom_out(self, actor=None, event=None, view=None):
		self.osm.zoom_out()
		
	def set_position(self, lat, lon, force=False):
		self.osm.gps_clear()
		self.osm.gps_add(lat, lon, heading=OsmGpsMap.MAP_INVALID);
		
		self.config["last_position"] = "%s/%s" % (lat, lon)
		
	def add_marker(self, key, color, lat, lon):
		"""add a new marker to the marker_layer
		
		key: a unique key
		color: a color from self.colors
		lat: latitude
		lon: longitude
		"""
		if lat == 0.0 and lon == 0.0:
			return
		try:
			marker = self.markers[key]
			self.update_marker(marker, key, lat, lon)
			return
		except KeyError:
			pass
		
		self.add_image(lat, lon, key, color)
		self.markers[key] = Marker(key, lat, lon, color)
		
	def add_image(self, lat, lon, key, color):
		if not self.occupy_position(lat, lon, key):
			return
		
		image = self.osm.image_add(lat, lon, self.textures[color])
		self.coordinates[lat][lon]["image"] = image
		
	def clear_position(self, lat, lon, key):
		self.coordinates[lat][lon]["markers"].remove(key)
		renew = False
		if len(self.coordinates[lat][lon]["markers"]) != 0:
			next = self.coordinates[lat][lon]["markers"][0]
			if self.markers[key].color != self.markers[next].color:
				renew = True
		else:
			next = None
		
		if next is None or renew is True:
			self.osm.image_remove(self.coordinates[lat][lon]["image"])
			del self.coordinates[lat][lon]["image"]
		
		if renew is True:
			next = self.coordinates[lat][lon]["markers"][0]
			self.add_image(lat, lon, next, self.markers[next].color)
		
	def update_marker(self, marker, key, lat, lon):
		if self.config["update_marker_positions"] is False:
			return
		old_lat = marker.lat
		old_lon = marker.lon
		if old_lat != lat or old_lon != lon:
			new = False
			try:
				if len(self.coordinates[lat][lon]["markers"]) > 0:
					self.coordinates[lat][lon]["markers"].append(key)
				else:
					new = True
			except KeyError:
				new = True
			
			if new == True:
				self.add_image(lat, lon, key, marker.color)
			
			marker.lat = lat
			marker.lon = lon
			self.clear_position(old_lat, old_lon, key)
			
	def occupy_position(self, lat, lon, key):
		try:
			if key in self.coordinates[lat][lon]["markers"]:
				return True
			self.coordinates[lat][lon]["markers"].append(key)
			if len(self.coordinates[lat][lon]["markers"]) == 1:
				return True
			else:
				return False
		except KeyError:
			if lat not in self.coordinates:
				self.coordinates[lat] = {lon: {"markers": [key, ]}}
				return True
			else:
				self.coordinates[lat][lon] = {"markers": [key, ]}
				return True
		
	def remove_marker(self, key):
		try:
			marker = self.markers[key]
		except KeyError:
			return
		
		self.clear_position(marker.lat, marker.lon, key)
		del self.markers[key]
		
	def stop_moving(self):
		self.osm.set_property("auto-center", False)
		
	def start_moving(self):
		self.osm.set_property("auto-center", True)
		lat, lon = self.config["last_position"].split("/")
		self.set_position(float(lat), float(lon))
		
	def on_map_pressed(self, actor, event):
		if event != None:
			self.osm.grab_focus()
			if event.x >= 32 and event.x < 48 and event.y >= 32 and event.y < 48:
				self.start_moving()
		
	def locate_marker(self, key):
		if key not in self.markers:
			print("marker %s not found" % key)
			return
			
		marker = self.markers[key]
		self.osm.set_center(marker.lat, marker.lon)
		crosshair_key = "locate"
		if crosshair_key in self.markers:
			self.osm.image_remove(self.markers[crosshair_key].image)
			del self.markers[crosshair_key]
		self.markers[crosshair_key] = Marker(key, marker.lat, marker.lon, "crosshair")
		self.markers[crosshair_key].image = self.osm.image_add(marker.lat, marker.lon, self.textures["crosshair"])
		
	def set_source(self, id):
		self.osm.download_cancel_all()
		old_id = self.config["source"]
		self.config["source"] = id
		if self.widget.get_parent():
			self.widget.get_parent().remove(self.widget)
		if old_id == "custom" and id != "custom":
			zoom = self.osm.get_property("zoom")
			self.init_osm()
			self.set_zoom(zoom)
			self.start_moving()
		
		if id == "openstreetmap-renderer":
			self.osm.set_property("map-source", OsmGpsMap.MapSource_t.OPENSTREETMAP_RENDERER)
		elif id == "custom":
			zoom = self.osm.get_property("zoom")
			self.init_osm()
			self.set_zoom(zoom)
			self.start_moving()
		else:
			id = "openstreetmap"
			self.osm.set_property("map-source", OsmGpsMap.MapSource_t.OPENSTREETMAP)
			self.config["source"] = id
		
class Marker:
	def __init__(self, key, lat, lon, color):
		self.key = key
		self.lat = lat
		self.lon = lon
		self.color = color
	
if __name__ == "__main__":
	import test
	test.map()
	Gtk.main()
