import os
import re
import glob
import numpy as np
import colormaps as cm

import matplotlib.pylab as plt
from mpl_toolkits.basemap import Basemap


#- Pretty units for some components.
UNIT_DICT = {
    "vp": r"$\frac{\mathrm{m}}{\mathrm{s}}$",
    "vsv": r"$\frac{\mathrm{m}}{\mathrm{s}}$",
    "vsh": r"$\frac{\mathrm{m}}{\mathrm{s}}$",
    "rho": r"$\frac{\mathrm{kg}^3}{\mathrm{m}^3}$",
    "rhoinv": r"$\frac{\mathrm{m}^3}{\mathrm{kg}^3}$",
    "vx": r"$\frac{\mathrm{m}}{\mathrm{s}}$",
    "vy": r"$\frac{\mathrm{m}}{\mathrm{s}}$",
    "vz": r"$\frac{\mathrm{m}}{\mathrm{s}}$",
}

#==============================================================================================
#- Class for fields (models, kernels, snapshots) in the SES3D format.
#==============================================================================================
class ses3d_fields(object):
	"""
	Class for reading and plotting 3D fields defined on the SEM grid of SES3D.
	"""

	def __init__(self, directory, field_type="earth_model"):
		"""
		__init__(self, directory, field_type="earth_model")

		Initiate the ses3d_fields class. Read available components. Admissible field_type's currently
		are "earth_model" and "velocity_snapshot".
		"""

		self.directory = directory
		self.field_type = field_type

		#- Read available Earth model files. ------------------------------------------------------
		if field_type == "earth_model":

			self.pure_components = ["A", "B", "C", "lambda", "mu", "rhoinv", "Q"]
			self.derived_components = ["vp", "vsh", "vsv", "rho"]

		#- Read available velocity snapshots. -----------------------------------------------------
		if field_type == "velocity_snapshot":

			self.pure_components = ["vx", "vy", "vz"]
			self.components = {}

		self.setup = self.read_setup()
		self.make_coordinates()

	#==============================================================================================
	#- Read the setup file.
	#==============================================================================================
	def read_setup(self):
		"""
		Read the setup file to get domain geometry.
		"""

		setup = {}

		#- Open setup file and read header. -------------------------------------------------------
		f = open('../INPUT/setup','r')
		lines = f.readlines()[1:]
		lines = [_i.strip() for _i in lines if _i.strip()]

		#- Read computational domain. -------------------------------------------------------------
		domain = {}
		domain["theta_min"] = float(lines.pop(0).split(' ')[0]) * np.pi / 180.0
		domain["theta_max"] = float(lines.pop(0).split(' ')[0]) * np.pi / 180.0
		domain["phi_min"] = float(lines.pop(0).split(' ')[0]) * np.pi / 180.0
		domain["phi_max"] = float(lines.pop(0).split(' ')[0]) * np.pi / 180.0
		domain["z_min"] = float(lines.pop(0).split(' ')[0])
		domain["z_max"] = float(lines.pop(0).split(' ')[0])
		setup["domain"] = domain

		#- Read computational setup. --------------------------------------------------------------
		lines.pop(0)
		lines.pop(0)
		lines.pop(0)

		elements = {}
		elements["nx_global"] = int(lines.pop(0).split(' ')[0])
		elements["ny_global"] = int(lines.pop(0).split(' ')[0])
		elements["nz_global"] = int(lines.pop(0).split(' ')[0])
		
		setup["lpd"] = int(lines.pop(0).split(' ')[0])

		procs = {}
		procs["px"] = int(lines.pop(0).split(' ')[0])
		procs["py"] = int(lines.pop(0).split(' ')[0])
		procs["pz"] = int(lines.pop(0).split(' ')[0])
		setup["procs"] = procs

		elements["nx"] = 1 + elements["nx_global"] / procs["px"]
		elements["ny"] = 1 + elements["ny_global"] / procs["py"]
		elements["nz"] = 1 + elements["nz_global"] / procs["pz"]

		setup["elements"] = elements

		#- Clean up. ------------------------------------------------------------------------------
		f.close()

		return setup

	#==============================================================================================
	#- Make coordinate lines for each chunk.
	#==============================================================================================
	def make_coordinates(self):
		"""
		Make the coordinate lines for the different processor boxes.
		"""

		n_procs = self.setup["procs"]["px"] * self.setup["procs"]["py"] * self.setup["procs"]["pz"]
		
		#- Boundaries of the processor blocks. ----------------------------------------------------
		width_theta = (self.setup["domain"]["theta_max"] - self.setup["domain"]["theta_min"]) / self.setup["procs"]["px"]
		width_phi = (self.setup["domain"]["phi_max"] - self.setup["domain"]["phi_min"]) / self.setup["procs"]["py"]
		width_z = (self.setup["domain"]["z_max"] - self.setup["domain"]["z_min"]) / self.setup["procs"]["pz"]

		boundaries_theta = np.arange(self.setup["domain"]["theta_min"],self.setup["domain"]["theta_max"]+width_theta,width_theta)
		boundaries_phi = np.arange(self.setup["domain"]["phi_min"],self.setup["domain"]["phi_max"]+width_phi,width_phi)
		boundaries_z = np.arange(self.setup["domain"]["z_min"],self.setup["domain"]["z_max"]+width_z,width_z)

		#- Make knot lines. -----------------------------------------------------------------------
		knot_x = self.get_GLL() + 1.0
		for ix in np.arange(self.setup["elements"]["nx"] - 1):
			knot_x = np.append(knot_x,self.get_GLL() + 1 + 2*(ix+1))

		knot_y = self.get_GLL() + 1.0
		for iy in np.arange(self.setup["elements"]["ny"] - 1):
			knot_y = np.append(knot_y,self.get_GLL() + 1 + 2*(iy+1))

		knot_z = self.get_GLL() + 1.0
		for iz in np.arange(self.setup["elements"]["nz"] - 1):
			knot_z = np.append(knot_z,self.get_GLL() + 1 + 2*(iz+1))

		knot_x = knot_x * width_theta / np.max(knot_x)
		knot_y = knot_y * width_phi / np.max(knot_y)
		knot_z = knot_z * width_z / np.max(knot_z)

		#- Loop over all processors. --------------------------------------------------------------
		self.theta = np.empty(shape=(n_procs,len(knot_x)))
		self.phi = np.empty(shape=(n_procs,len(knot_y)))
		self.z = np.empty(shape=(n_procs,len(knot_z)))
		p = 0

		for iz in np.arange(self.setup["procs"]["pz"]):
			for iy in np.arange(self.setup["procs"]["py"]):
				for ix in np.arange(self.setup["procs"]["px"]):
			
					self.theta[p,:] = boundaries_theta[ix] + knot_x
					self.phi[p,:] = boundaries_phi[iy] + knot_y
					self.z[p,: :-1] = boundaries_z[iz] + knot_z

					p += 1
			
	#==============================================================================================
	#- Get GLL points.
	#==============================================================================================
	def get_GLL(self):
		"""
		Set GLL points for a given Lagrange polynomial degree.
		"""

		if self.setup["lpd"] == 2:
			knots = np.array([-1.0, 0.0, 1.0])
		elif self.setup["lpd"] == 3:
			knots = np.array([-1.0, -0.4472135954999579, 0.4472135954999579, 1.0])
		elif self.setup["lpd"] == 4:
			knots = np.array([-1.0, -0.6546536707079772, 0.0, 0.6546536707079772, 1.0])
		elif self.setup["lpd"] == 5:
			knots = np.array([-1.0, -0.7650553239294647, -0.2852315164806451, 0.2852315164806451, 0.7650553239294647, 1.0])
		elif self.setup["lpd"] == 6:
			knots = np.array([-1.0, -0.8302238962785670, -0.4688487934707142, 0.0, 0.4688487934707142, 0.8302238962785670, 1.0])
		elif self.setup["lpd"] == 7:
			knots = np.array([-1.0, -0.8717401485096066, -0.5917001814331423, -0.2092992179024789, 0.2092992179024789, 0.5917001814331423, 0.8717401485096066, 1.0])

		return knots

	#==============================================================================================
	#- Compose filenames.
	#==============================================================================================
	def compose_filenames(self, component, proc_number, iteration=0):
		"""
		Build filenames for the different field types.
		"""

		#- Earth models. --------------------------------------------------------------------------
		if self.field_type == "earth_model":
			filename = os.path.join(self.directory, component+str(proc_number))

		#-Velocity field snapshots. ---------------------------------------------------------------
		elif self.field_type == "velocity_snapshot":
			filename = os.path.join(self.directory, component+"_"+str(proc_number)+"_"+str(iteration))

		return filename

	#==============================================================================================
	#- Read single box.
	#==============================================================================================
	def read_single_box(self, component, proc_number, iteration=0):
		"""
		Read the field from one single processor box.
		"""

		#- Shape of the Fortran binary file. ------------------------------------------------------
		shape = (self.setup["elements"]["nx"],self.setup["elements"]["ny"],self.setup["elements"]["nz"],self.setup["lpd"]+1,self.setup["lpd"]+1,self.setup["lpd"]+1)

		#- Read and compute the proper components. ------------------------------------------------
		if component in self.pure_components:
			filename = self.compose_filenames(component, proc_number, iteration)
			with open(filename, "rb") as open_file:
				field = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")

		elif component in self.derived_components:
			#- rho 
			if component == "rho":
				filename = self.compose_filenames("rhoinv", proc_number, 0)
				with open(filename, "rb") as open_file:
					field = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")
				field = 1.0 / field

			#- vp
			if component == "vp":
				filename1 = self.compose_filenames("lambda", proc_number, 0)
				filename2 = self.compose_filenames("mu", proc_number, 0)
				filename3 = self.compose_filenames("rhoinv", proc_number, 0)
				with open(filename1, "rb") as open_file:
					field1 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")
				with open(filename2, "rb") as open_file:
					field2 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")
				with open(filename3, "rb") as open_file:
					field3 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")

				field = np.sqrt((field1 + 2 * field2) * field3)

			#- vsh
			if component == "vsh":
				filename1 = self.compose_filenames("mu", proc_number, 0)
				filename2 = self.compose_filenames("rhoinv", proc_number, 0)
				with open(filename1, "rb") as open_file:
					field1 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")
				with open(filename2, "rb") as open_file:
					field2 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")

				field = np.sqrt(field1 * field2)

			#- vsv
			if component == "vsv":
				filename1 = self.compose_filenames("mu", proc_number, 0)
				filename2 = self.compose_filenames("rhoinv", proc_number, 0)
				filename3 = self.compose_filenames("B", proc_number, 0)
				with open(filename1, "rb") as open_file:
					field1 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")
				with open(filename2, "rb") as open_file:
					field2 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")
				with open(filename3, "rb") as open_file:
					field3 = np.ndarray(shape, buffer=open_file.read()[4:-4], dtype="float32", order="F")

				field = np.sqrt((field1 + field3) * field2)

		
		#- Reshape the array. ---------------------------------------------------------------------
		new_shape = [_i * _j for _i, _j in zip(shape[:3], shape[3:])]
		field = np.rollaxis(np.rollaxis(field, 3, 1), 3, self.setup["lpd"] + 1)
		field = field.reshape(new_shape, order="C")

		return field

	#==============================================================================================
	#- Plot depth slice.
	#==============================================================================================
	def plot_depth_slice(self, component, depth, valmin, valmax, iteration=0, verbose=True, res="i"):
		"""
		plot_depth_slice(self, component, depth, valmin, valmax, iteration=0, verbose=True, res="i")

		Plot depth slices of field component at depth "depth" with colourbar ranging between "valmin" and "valmax".
		The resolution of the coastline is "res" (c, l, i, h, f).

		The currently available "components" are:
			Material parameters: A, B, C, mu, lambda, rhoinv, vp, vsh, vsv, rho
			Velocity field snapshots: vx, vy, vz
		"""


		#- Some initialisations. ------------------------------------------------------------------
		n_procs = self.setup["procs"]["px"] * self.setup["procs"]["py"] * self.setup["procs"]["pz"]
		radius = 1000.0 * (6371.0 - depth)

		vmax = float("-inf")
		vmin = float("inf")

		lat_min = 90.0 - self.setup["domain"]["theta_max"]*180.0/np.pi
		lat_max = 90.0 - self.setup["domain"]["theta_min"]*180.0/np.pi
		lon_min = self.setup["domain"]["phi_min"]*180.0/np.pi
		lon_max = self.setup["domain"]["phi_max"]*180.0/np.pi

		d_lon = np.round((lon_max-lon_min)/10.0)
		d_lat = np.round((lat_max-lat_min)/10.0)

		#- Set up the map. ------------------------------------------------------------------------
		if (lat_max-lat_min) > 30.0:
			m = Basemap(projection='ortho', lon_0=(lon_max+lon_min)/2.0, lat_0=(lat_max+lat_min)/2.0, resolution=res)
			m.drawparallels(np.arange(-80.0,80.0,10.0),labels=[1,0,0,1])
			m.drawmeridians(np.arange(-170.0,170.0,10.0),labels=[1,0,0,1])	
		else:
			m=Basemap(projection='merc',llcrnrlat=lat_min,urcrnrlat=lat_max,llcrnrlon=lon_min,urcrnrlon=lon_max,lat_ts=20,resolution=res)
			m.drawparallels(np.arange(np.round(lat_min),np.round(lat_max),d_lat),labels=[1,0,0,1])
			m.drawmeridians(np.arange(np.round(lon_min),np.round(lon_max),d_lon),labels=[1,0,0,1])

		m.drawcoastlines()
		m.fillcontinents("0.9", zorder=0)
		m.drawmapboundary(fill_color="white")
		m.drawcountries()

		#- Loop over processor boxes and check if depth falls within the volume. ------------------
		for p in range(n_procs):

			if (radius >= self.z[p,:].min()) & (radius <= self.z[p,:].max()):

				#- Read this field and make lats & lons. ------------------------------------------
				field = self.read_single_box(component,p,iteration)
				lats = 90.0 - self.theta[p,:] * 180.0 / np.pi
				lons = self.phi[p,:] * 180.0 / np.pi
				lon, lat = np.meshgrid(lons, lats)

				#- Find the depth index and plot for this one box. --------------------------------
				idz=min(np.where(min(np.abs(self.z[p,:]-radius))==np.abs(self.z[p,:]-radius))[0])

				#- Find min and max values. -------------------------------------------------------

				vmax = max(vmax, field[:,:,idz].max())
				vmin = min(vmin, field[:,:,idz].min())

				#- Make lats and lons. --------------------------------------------------------------------
				lats = 90.0 - self.theta[p,:] * 180.0 / np.pi
				lons = self.phi[p,:] * 180.0 / np.pi
				lon, lat = np.meshgrid(lons, lats)

				#- Make a nice colourmap. -----------------------------------------------------------------
				my_colormap=cm.make_colormap({0.0:[0.1,0.0,0.0], 0.2:[0.8,0.0,0.0], 0.3:[1.0,0.7,0.0],0.48:[0.92,0.92,0.92], 0.5:[0.92,0.92,0.92], 0.52:[0.92,0.92,0.92], 0.7:[0.0,0.6,0.7], 0.8:[0.0,0.0,0.8], 1.0:[0.0,0.0,0.1]})

				x, y = m(lon, lat)
				im = m.pcolormesh(x, y, field[:,:,idz], cmap=my_colormap, vmin=valmin,vmax=valmax)

		#- Add colobar and title. ---------------------------------------------------------
		cb = m.colorbar(im, "right", size="3%", pad='2%')
		if component in UNIT_DICT:
			cb.set_label(UNIT_DICT[component], fontsize="x-large", rotation=0)
	
		plt.suptitle("Depth slice of %s at %i km" % (component, int(self.z[p,idz]/1000.0)), size="large")

		plt.show()

		if verbose == True:
			print "minimum value: "+str(vmin)+", maximum value: "+str(vmax)
				




