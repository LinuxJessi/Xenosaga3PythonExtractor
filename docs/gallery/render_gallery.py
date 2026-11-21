# Origin: copied from the Episode II kit (Xenosaga2PythonExtractor/docs/gallery/
# render_gallery.py); the only change here is that the World.use_nodes
# DeprecationWarning (Blender 5.x) is silenced.
# Renders a gallery image from a kit-made .glb with Blender (headless):
#   blender -b --python render_gallery.py -- model.glb out.png char|map
# char = 3/4 portrait of a figure; map = raised 3/4 view with sky shells hidden and backface culling on.
import bpy, sys, math, mathutils
argv = sys.argv[sys.argv.index("--")+1:]
glb, out, kind = argv[0], argv[1], argv[2]
engine = argv[3] if len(argv)>3 else 'BLENDER_EEVEE'
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
for o in list(bpy.data.objects):
    if o.name.startswith("Icosphere"): bpy.data.objects.remove(o, do_unlink=True)
    elif o.type=='ARMATURE': o.hide_viewport=True; o.hide_render=True
if kind=='map':
    for m in bpy.data.materials: m.use_backface_culling=True
meshes=[o for o in bpy.data.objects if o.type=='MESH']
def diag(o):
    ws=[o.matrix_world@mathutils.Vector(c) for c in o.bound_box]
    return (mathutils.Vector([max(w[i] for w in ws) for i in range(3)])-mathutils.Vector([min(w[i] for w in ws) for i in range(3)])).length
import numpy as np
if kind=='map':
    ds=sorted(((diag(o),len(o.data.polygons)) for o in meshes))
    tot=sum(n for _,n in ds); acc=0; med=ds[-1][0]
    for d,n in ds:
        acc+=n
        if acc>=tot/2: med=d; break
    lim=med*5
    for o in meshes:
        if diag(o)>lim: o.hide_render=True
    meshes=[o for o in meshes if diag(o)<=lim] or meshes
pts=[]
for o in meshes:
    M=np.array(o.matrix_world)
    v=np.array([list(x.co)+[1] for x in o.data.vertices])
    pts.append((v@M.T)[:,:3])
P=np.concatenate(pts)
lo,hi=(np.percentile(P,3,axis=0),np.percentile(P,97,axis=0)) if kind=='map' else (P.min(0),P.max(0))
mn=mathutils.Vector(lo.tolist()); mx=mathutils.Vector(hi.tolist())
ctr=(mn+mx)/2; size=mx-mn
sc=bpy.context.scene
sc.render.engine=engine
sc.render.resolution_x, sc.render.resolution_y = (1000,1400) if kind=='char' else (1600,1000)
sc.render.film_transparent=False
w=bpy.data.worlds.new("w")
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning); w.use_nodes=True
bg=w.node_tree.nodes["Background"]; bg.inputs[0].default_value=(0.09,0.10,0.13,1); bg.inputs[1].default_value=1.0
sc.world=w
cam=bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera=cam
if kind=='char':
    cam.data.lens=70; dist=max(size.z*0.8/ (2*math.tan(math.atan(12/70))), 1)*1.0
    ang=math.radians(-28); tgt=ctr
    cam.location=tgt+mathutils.Vector((math.sin(ang)*dist, -math.cos(ang)*dist, 0))
else:
    cam.data.lens=28; dist=max(size.x,size.y,size.z)*1.25
    ang=math.radians(-35); tgt=ctr
    cam.location=tgt+mathutils.Vector((math.sin(ang)*dist, -math.cos(ang)*dist*0.9, dist*0.55))
    cam.data.clip_end=dist*10
d=tgt-cam.location
cam.rotation_euler=d.to_track_quat('-Z','Y').to_euler()
# lights
for loc,e in (((4,-5,6),3.0),((-5,-3,2),1.2)):
    l=bpy.data.objects.new("l",bpy.data.lights.new("l",'SUN')); l.data.energy=e
    l.rotation_euler=(mathutils.Vector((0,0,0))-mathutils.Vector(loc)).to_track_quat('-Z','Y').to_euler()
    sc.collection.objects.link(l)
if engine=='BLENDER_WORKBENCH':
    sc.display.shading.light='STUDIO'; sc.display.shading.color_type='TEXTURE'
sc.render.filepath=out; sc.render.image_settings.file_format='PNG'
bpy.ops.render.render(write_still=True)
