extends Node3D
## Godot spike: builds the shared benchmark scene from ../shared/scene.json and renders frames
## [start, start+count) at 4K, piping raw frames into ffmpeg. Time = frame / fps (never wall-clock).
## User args (after `--`): --start N --count N --out file.mp4 --hash file.json --stills a,b --stills-dir dir
##   --ffmpeg path --sdfgi --no-ssao --no-glow

const TAU_F := TAU

var S: Dictionary
var opts := {"start": 0, "count": 300, "out": "", "hash": "", "stills": [], "stills_dir": "", "ffmpeg": "ffmpeg",
	"sdfgi": false, "ssao": true, "glow": true, "no_capture": false}
var tex := {}
var frame_i := 0
var written := 0
var pipe: Dictionary = {}
var hashes := {}
var t_first := 0
var rain_mm: MultiMesh
var slide_mm: MultiMesh
var fan_blades: Node3D
var pet_parts := {}


func _ready() -> void:
	_parse_args()
	var shared := ProjectSettings.globalize_path("res://").path_join("../shared")
	S = JSON.parse_string(FileAccess.get_file_as_string(shared.path_join("scene.json")))
	for n in ["floor_planks", "wall_plaster", "wood_dark", "rug", "fur", "shade", "facade", "facade_emit"]:
		var img := Image.load_from_file(shared.path_join("textures/%s.png" % n))
		img.generate_mipmaps()
		tex[n] = ImageTexture.create_from_image(img)
	_build()
	frame_i = opts.start
	_apply(frame_i)
	RenderingServer.frame_post_draw.connect(_on_post_draw)
	print("renderer: %s | %s | godot %s" % [RenderingServer.get_video_adapter_name(), RenderingServer.get_current_rendering_driver_name(), Engine.get_version_info().string])


func _parse_args() -> void:
	var args := OS.get_cmdline_user_args()
	var i := 0
	while i < args.size():
		var k: String = args[i]
		match k:
			"--start": opts.start = int(args[i + 1]); i += 1
			"--count": opts.count = int(args[i + 1]); i += 1
			"--out": opts.out = args[i + 1]; i += 1
			"--hash": opts.hash = args[i + 1]; i += 1
			"--stills":
				opts.stills = Array(args[i + 1].split(",")).map(func(s): return int(s)); i += 1
			"--stills-dir": opts.stills_dir = args[i + 1]; i += 1
			"--ffmpeg": opts.ffmpeg = args[i + 1]; i += 1
			"--sdfgi": opts.sdfgi = true
			"--no-ssao": opts.ssao = false
			"--no-glow": opts.glow = false
			"--no-capture": opts.no_capture = true
		i += 1


func _mat(texname, emissive := 0.0, emissive_tex := "", emissive_color := "#ffffff") -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_texture = tex[texname]
	m.texture_filter = BaseMaterial3D.TEXTURE_FILTER_NEAREST_WITH_MIPMAPS_ANISOTROPIC
	m.roughness = 0.92
	if emissive > 0.0:
		m.emission_enabled = true
		m.emission = Color(emissive_color)
		m.emission_energy_multiplier = emissive
		m.emission_texture = tex[emissive_tex if emissive_tex != "" else texname]
		m.emission_operator = BaseMaterial3D.EMISSION_OP_MULTIPLY
	return m


# Box with UVs in world block units (16 texels per block). Godot front faces wind clockwise and
# image v grows downward, so indices and v are flipped relative to the three.js builder.
func _add_box(st: SurfaceTool, mn: Array, mx: Array, uvo := [0.0, 0.0, 0.0]) -> void:
	var x0: float = mn[0]; var y0: float = mn[1]; var z0: float = mn[2]
	var x1: float = mx[0]; var y1: float = mx[1]; var z1: float = mx[2]
	var ox: float = uvo[0]; var oy: float = uvo[1]; var oz: float = uvo[2]
	var faces := [
		[Vector3(1, 0, 0), [Vector3(x1, y0, z1), Vector3(x1, y0, z0), Vector3(x1, y1, z0), Vector3(x1, y1, z1)], 0],
		[Vector3(-1, 0, 0), [Vector3(x0, y0, z0), Vector3(x0, y0, z1), Vector3(x0, y1, z1), Vector3(x0, y1, z0)], 1],
		[Vector3(0, 1, 0), [Vector3(x0, y1, z1), Vector3(x1, y1, z1), Vector3(x1, y1, z0), Vector3(x0, y1, z0)], 2],
		[Vector3(0, -1, 0), [Vector3(x0, y0, z0), Vector3(x1, y0, z0), Vector3(x1, y0, z1), Vector3(x0, y0, z1)], 3],
		[Vector3(0, 0, 1), [Vector3(x0, y0, z1), Vector3(x1, y0, z1), Vector3(x1, y1, z1), Vector3(x0, y1, z1)], 4],
		[Vector3(0, 0, -1), [Vector3(x1, y0, z0), Vector3(x0, y0, z0), Vector3(x0, y1, z0), Vector3(x1, y1, z0)], 5],
	]
	for f in faces:
		var n: Vector3 = f[0]
		var vs: Array = f[1]
		var uvs := []
		for p: Vector3 in vs:
			var uv: Vector2
			match f[2]:
				0: uv = Vector2(-(p.z - oz), p.y - oy)
				1: uv = Vector2(p.z - oz, p.y - oy)
				2: uv = Vector2(p.x - ox, -(p.z - oz))
				3: uv = Vector2(p.x - ox, p.z - oz)
				4: uv = Vector2(p.x - ox, p.y - oy)
				_: uv = Vector2(-(p.x - ox), p.y - oy)
			uvs.append(Vector2(uv.x, -uv.y))
		for idx in [0, 2, 1, 0, 3, 2]:
			st.set_normal(n)
			st.set_uv(uvs[idx])
			st.add_vertex(vs[idx])


func _box_mesh(size: Array, mat: Material) -> MeshInstance3D:
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	var h := [size[0] / 2.0, size[1] / 2.0, size[2] / 2.0]
	_add_box(st, [-h[0], -h[1], -h[2]], h, [-h[0], -h[1], -h[2]])
	st.set_material(mat)
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	return mi


func _build() -> void:
	var pal: Dictionary = S.palette
	# Static boxes merged per material key.
	var groups := {}
	for b: Dictionary in S.boxes:
		var key: String = b.tex if b.tex != null else "color:" + b.color
		if not groups.has(key):
			var st := SurfaceTool.new()
			st.begin(Mesh.PRIMITIVE_TRIANGLES)
			groups[key] = {"b": b, "st": st}
		_add_box(groups[key].st, b.min, b.max)
	for key in groups:
		var b: Dictionary = groups[key].b
		var mat: StandardMaterial3D
		if b.tex == null:
			mat = StandardMaterial3D.new()
			mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
			mat.albedo_color = Color(b.color)
			mat.disable_fog = true
		else:
			mat = _mat(b.tex, b.get("emissive", 0.0), b.get("emissiveTex", ""), b.get("emissiveColor", "#ffffff"))
		var st: SurfaceTool = groups[key].st
		st.set_material(mat)
		var mi := MeshInstance3D.new()
		mi.mesh = st.commit()
		if key == "facade" or key == "shade":
			mi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
		add_child(mi)

	# Camera.
	var cam := Camera3D.new()
	cam.fov = S.camera.fovY
	cam.near = 0.05
	cam.far = 400.0
	add_child(cam)
	cam.look_at_from_position(_v(S.camera.pos), _v(S.camera.target))
	cam.current = true

	# Environment: AgX, glow, SSAO, exponential fog, faint warm ambient.
	var env := Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color("#1b1630")
	env.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.ambient_light_color = Color("#6a4428")
	env.ambient_light_energy = 0.45
	env.tonemap_mode = Environment.TONE_MAPPER_AGX
	env.glow_enabled = opts.glow
	env.glow_intensity = 0.8
	env.glow_bloom = 0.05
	env.glow_hdr_threshold = 0.9
	env.glow_blend_mode = Environment.GLOW_BLEND_MODE_SOFTLIGHT
	env.ssao_enabled = opts.ssao
	env.ssao_radius = 1.2
	env.ssao_intensity = 2.0
	env.fog_enabled = true
	env.fog_mode = Environment.FOG_MODE_EXPONENTIAL
	env.fog_light_color = Color(pal.fog)
	env.fog_density = 0.022
	env.fog_sky_affect = 0.0
	if opts.sdfgi:
		env.sdfgi_enabled = true
		env.sdfgi_energy = 0.8
	var we := WorldEnvironment.new()
	we.environment = env
	add_child(we)

	var lamp := OmniLight3D.new()
	lamp.position = _v(S.lamp.pos)
	lamp.light_color = Color(pal.lampLight)
	lamp.light_energy = 3.2
	lamp.omni_range = S.lamp.range
	lamp.omni_attenuation = 1.4
	lamp.shadow_enabled = true
	lamp.shadow_blur = 2.0
	lamp.shadow_opacity = 0.8
	add_child(lamp)
	var win := SpotLight3D.new()
	win.light_color = Color(pal.windowLight)
	win.light_energy = 6.0
	win.spot_range = 40.0
	win.spot_angle = 32.0
	win.shadow_enabled = true
	add_child(win)
	win.look_at_from_position(Vector3(4, 7, -9), Vector3(4, 0, 4))

	# Glass + drops.
	var g: Dictionary = S.window
	var glass := MeshInstance3D.new()
	var qm := QuadMesh.new()
	qm.size = Vector2(g.x[1] - g.x[0], g.y[1] - g.y[0])
	glass.mesh = qm
	var gm := StandardMaterial3D.new()
	gm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	gm.albedo_color = Color(pal.glassTint, 0.18)
	gm.roughness = 0.15
	gm.cull_mode = BaseMaterial3D.CULL_DISABLED
	glass.material_override = gm
	glass.position = Vector3((g.x[0] + g.x[1]) / 2.0, (g.y[0] + g.y[1]) / 2.0, g.glassZ)
	glass.sorting_offset = 2.0
	add_child(glass)
	var dm := StandardMaterial3D.new()
	dm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	dm.albedo_color = Color("#9fa6c0", 0.35)
	dm.roughness = 0.1
	dm.emission_enabled = true
	dm.emission = Color("#2a2438")
	var drop_box := BoxMesh.new()
	drop_box.size = Vector3(1, 1, 1.0 / 32.0)
	drop_box.material = dm
	var beads := MultiMesh.new()
	beads.transform_format = MultiMesh.TRANSFORM_3D
	beads.mesh = drop_box
	beads.instance_count = S.drops.beads.size()
	for i in S.drops.beads.size():
		var bd: Array = S.drops.beads[i]
		beads.set_instance_transform(i, Transform3D(Basis.from_scale(Vector3(bd[2], bd[2], 1)), Vector3(bd[0], bd[1], g.glassZ + 0.03)))
	var bmi := MultiMeshInstance3D.new()
	bmi.multimesh = beads
	add_child(bmi)
	slide_mm = MultiMesh.new()
	slide_mm.transform_format = MultiMesh.TRANSFORM_3D
	slide_mm.mesh = drop_box
	slide_mm.instance_count = S.drops.slide.size()
	var smi := MultiMeshInstance3D.new()
	smi.multimesh = slide_mm
	smi.custom_aabb = AABB(Vector3(0, 0, -2), Vector3(10, 6, 4))
	add_child(smi)

	# Rain.
	var rm := StandardMaterial3D.new()
	rm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	rm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	rm.albedo_color = Color(pal.rain, 0.38)
	var rain_box := BoxMesh.new()
	rain_box.size = Vector3(1.0 / 16.0, 1, 1.0 / 16.0)
	rain_box.material = rm
	rain_mm = MultiMesh.new()
	rain_mm.transform_format = MultiMesh.TRANSFORM_3D
	rain_mm.mesh = rain_box
	rain_mm.instance_count = S.rain.streaks.size()
	var rmi := MultiMeshInstance3D.new()
	rmi.multimesh = rain_mm
	rmi.custom_aabb = AABB(Vector3(-20, -20, -20), Vector3(50, 40, 25))
	rmi.cast_shadow = GeometryInstance3D.SHADOW_CASTING_SETTING_OFF
	add_child(rmi)

	# Ceiling fan.
	var wood := _mat("wood_dark")
	var fan := Node3D.new()
	fan.position = _v(S.fan.pos)
	var drop: float = S.fan.drop
	var rod := _box_mesh([0.0625, drop, 0.0625], wood)
	rod.position.y = -drop / 2.0
	var motor := _box_mesh([0.3, 0.18, 0.3], wood)
	motor.position.y = -drop
	fan_blades = Node3D.new()
	fan_blades.position.y = -drop
	for i in int(S.fan.blades):
		var arm := Node3D.new()
		arm.rotation.y = float(i) / S.fan.blades * TAU_F
		var blade := _box_mesh(S.fan.blade, wood)
		blade.position.x = S.fan.blade[0] / 2.0 + 0.12
		arm.add_child(blade)
		fan_blades.add_child(arm)
	fan.add_child(rod)
	fan.add_child(motor)
	fan.add_child(fan_blades)
	add_child(fan)

	# Pet.
	var fur := _mat("fur")
	fur.roughness = 0.95
	var pet := Node3D.new()
	pet.position = _v(S.pet.origin)
	pet.rotation.y = S.pet.yaw
	for p: Dictionary in S.pet.parts:
		var m := _box_mesh(p.size, fur)
		pet_parts[p.name] = m
		pet.add_child(m)
	add_child(pet)


func _v(a: Array) -> Vector3:
	return Vector3(a[0], a[1], a[2])


func _smooth(v: float) -> float:
	return v * v * (3.0 - 2.0 * v)


func _euler_basis(e: Vector3) -> Basis:
	# Matches three.js Euler 'XYZ': R = Rx * Ry * Rz.
	return Basis(Vector3.RIGHT, e.x) * Basis(Vector3.UP, e.y) * Basis(Vector3.BACK, e.z)


func _apply(frame: int) -> void:
	var L: float = S.loopSeconds
	var loop_frames := int(round(L * S.fps))
	var t: float = float(frame % loop_frames) / S.fps

	fan_blades.rotation.y = -TAU_F * S.fan.revsPerLoop * (t / L)

	var y_top: float = S.rain.yTop
	var y_bot: float = S.rain.yBottom
	var tilt: float = S.rain.tilt
	var rb := Basis(Vector3.BACK, tilt)
	var streaks: Array = S.rain.streaks
	for i in streaks.size():
		var s: Array = streaks[i]
		var k := fposmod(s[2] + s[3] * t / L, 1.0)
		var y := y_top - k * (y_top - y_bot)
		rain_mm.set_instance_transform(i, Transform3D(rb * Basis.from_scale(Vector3(1, s[4], 1)), Vector3(s[0] + (y_top - y) * tan(tilt), y, s[1])))

	var g: Dictionary = S.window
	var slide: Array = S.drops.slide
	for i in slide.size():
		var d: Array = slide[i]
		var k := fposmod(d[1] + d[2] * t / L, 1.0)
		var y: float = g.y[1] - 0.1 - _smooth(k) * (g.y[1] - g.y[0] - 0.2)
		slide_mm.set_instance_transform(i, Transform3D(Basis.from_scale(Vector3(d[3], d[3] * 1.6, 1)), Vector3(d[0], y, g.glassZ + 0.035)))

	var s := 0.0
	for e: Array in S.pet.schedule:
		var a: float = e[0]
		var b: float = e[1]
		if t >= a and t < b:
			var k := _smooth((t - a) / (b - a))
			s = k if e[2] == "lie" else 1.0 - k
			break
		if t >= b:
			s = 1.0 if e[3] == "sit" else 0.0
	for p: Dictionary in S.pet.parts:
		if p.has("follow"):
			continue
		var m: MeshInstance3D = pet_parts[p.name]
		var ea := _axis_vec(p.lie.rot)
		var eb := _axis_vec(p.sit.rot)
		var e := ea.lerp(eb, s)
		if p.has("look"):
			e.y += p.look * s * sin(TAU_F * t / L)
		var pos := _v(p.lie.p).lerp(_v(p.sit.p), s)
		if p.has("breathe"):
			pos.y += p.breathe * sin(TAU_F * 4.0 * t / L)
		m.transform = Transform3D(_euler_basis(e), pos)
	for p: Dictionary in S.pet.parts:
		if not p.has("follow"):
			continue
		var head: MeshInstance3D = pet_parts[p.follow]
		pet_parts[p.name].transform = Transform3D(head.basis, head.basis * _v(p.offset) + head.position)


func _axis_vec(rot: Array) -> Vector3:
	var v := Vector3.ZERO
	v["xyz".find(rot[0])] = rot[1]
	return v


func _start_pipe(img: Image) -> void:
	var fmt := "rgba" if img.get_format() == Image.FORMAT_RGBA8 else "rgb24"
	var args := ["-hide_banner", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", fmt,
		"-s", "%dx%d" % [img.get_width(), img.get_height()], "-r", str(S.fps), "-i", "-",
		"-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
		"-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
		"-c:v", "hevc_nvenc", "-preset", "p5", "-tune", "hq", "-rc", "vbr", "-cq", "19", "-b:v", "0",
		"-maxrate", "80M", "-bufsize", "160M", "-tag:v", "hvc1", "-movflags", "+faststart", opts.out]
	pipe = OS.execute_with_pipe(opts.ffmpeg, args, false)


func _on_post_draw() -> void:
	if written >= opts.count:
		return
	if opts.no_capture:
		if written == 0:
			t_first = Time.get_ticks_usec()
		written += 1
		frame_i += 1
		if written >= opts.count:
			_finish(Image.create(1, 1, false, Image.FORMAT_RGB8))
		else:
			_apply(frame_i)
		return
	var img := get_viewport().get_texture().get_image()
	if written == 0:
		t_first = Time.get_ticks_usec()
		if opts.out != "":
			_start_pipe(img)
	var data := img.get_data()
	if opts.hash != "":
		var hc := HashingContext.new()
		hc.start(HashingContext.HASH_SHA256)
		hc.update(data)
		hashes[str(frame_i)] = hc.finish().hex_encode()
	if opts.stills.has(frame_i):
		DirAccess.make_dir_recursive_absolute(opts.stills_dir)
		img.save_png(opts.stills_dir.path_join("frame_%05d.png" % frame_i))
	if not pipe.is_empty():
		pipe.stdio.store_buffer(data)
	written += 1
	frame_i += 1
	if written >= opts.count:
		_finish(img)
	else:
		_apply(frame_i)


func _finish(img: Image) -> void:
	var render_s := float(Time.get_ticks_usec() - t_first) / 1e6
	if not pipe.is_empty():
		pipe.stdio.close()
		while OS.is_process_running(pipe.pid):
			OS.delay_msec(20)
	var total_s := float(Time.get_ticks_usec() - t_first) / 1e6
	if opts.hash != "":
		var f := FileAccess.open(opts.hash, FileAccess.WRITE)
		f.store_string(JSON.stringify(hashes, " "))
		f.close()
	print(JSON.stringify({"engine": "godot", "renderer": RenderingServer.get_video_adapter_name(),
		"driver": RenderingServer.get_current_rendering_driver_name(), "size": [img.get_width(), img.get_height()],
		"format": img.get_format(), "frames": written, "renderSec": snappedf(render_s, 0.01), "wallSec": snappedf(total_s, 0.01),
		"fps": snappedf(written / total_s, 0.01)}))
	get_tree().quit()
