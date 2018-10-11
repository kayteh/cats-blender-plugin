# MIT License

# Copyright (c) 2017 GiveMeAllYourCats

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the 'Software'), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED 'AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

# Code author: Shotariya
# Repo: https://github.com/Grim-es/shotariya
# Code author: Neitri
# Repo: https://github.com/netri/blender_neitri_tools
# Edits by: GiveMeAllYourCats, Hotox

import bpy
import copy

import tools.common
import tools.translate
import tools.armature_bones as Bones
import mmd_tools_local.operators.morph

import math
from mathutils import Matrix

mmd_tools_installed = True


class FixArmature(bpy.types.Operator):
    bl_idname = 'armature.fix'
    bl_label = 'Fix Model'
    bl_description = 'Automatically:\n' \
                     '- Reparents bones\n' \
                     '- Removes unnecessary bones, objects, groups & constraints\n' \
                     '- Translates and renames bones & objects\n' \
                     '- Merges weight paints\n' \
                     '- Corrects the hips\n' \
                     '- Joins meshes\n' \
                     '- Converts morphs into shapes\n' \
                     '- Corrects shading'

    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if tools.common.get_armature() is None:
            return False

        if len(tools.common.get_armature_objects()) == 0:
            return False

        return True

    def execute(self, context):
        armature = tools.common.set_default_stage()

        # VRM mesh fixes need to be done early
        self.report({'INFO'}, 'checking for VRM for early fixes')
        vrm_root = False
        try:
            arm_items = armature.pose.bones.items()
            if arm_items[0][0] == 'Root' and arm_items[1][0] == 'Global' and arm_items[2][0] == 'Position':
                vrm_root = arm_items[0][1]
                self.report({'INFO'}, 'VRM check passed, fixing model.')
            else:
                self.report({'INFO'}, 'VRM check failed')
        except AttributeError as e:
            self.report({'WARNING'}, 'VRM check failed w/ error', e)

        if vrm_root != False:
            meshes = tools.common.get_meshes_objects(mode=2)
        
            for mesh in meshes:
                if mesh.name == 'Body' or mesh.name == 'Face' or mesh.name.startswith('Hair'):
                    # Move these meshes under the armature, possibly others.
                    mesh.parent = armature
        
            for obj in bpy.data.objects:
                if obj.name == 'Hairs' or obj.name == 'secondary':
                    tools.common.delete_hierarchy(obj)
        
            self.report({'INFO'}, 'Performed VRM early fixes, moved body, face, and hair meshes under armature, deleted ephemeral transforms.')
        

        if len(tools.common.get_meshes_objects()) == 0:
            self.report({'ERROR'}, 'No mesh inside the armature found!')
            return {'CANCELLED'}

        print('\nFixing Model:\n')

        wm = bpy.context.window_manager

        # Check if bone matrix == world matrix, important for xps models
        x_cord, y_cord, z_cord, fbx = tools.common.get_bone_orientations()


        # Add rename bones to reweight bones
        temp_rename_bones = copy.deepcopy(Bones.bone_rename)
        temp_reweight_bones = copy.deepcopy(Bones.bone_reweight)
        temp_list_reweight_bones = copy.deepcopy(Bones.bone_list_weight)
        temp_list_reparent_bones = copy.deepcopy(Bones.bone_list_parenting)

        for key, value in Bones.bone_rename_fingers.items():
            temp_rename_bones[key] = value

        for key, value in temp_rename_bones.items():
            if key == 'Spine':
                continue
            list = temp_reweight_bones.get(key)
            if not list:
                temp_reweight_bones[key] = value
            else:
                for name in value:
                    if name not in list:
                        temp_reweight_bones.get(key).append(name)

        # Count objects for loading bar
        steps = 0
        for key, value in temp_rename_bones.items():
            if '\Left' in key or '\L' in key:
                steps += 2 * len(value)
            else:
                steps += len(value)
        for key, value in temp_reweight_bones.items():
            if '\Left' in key or '\L' in key:
                steps += 2 * len(value)
            else:
                steps += len(value)
        steps += len(temp_list_reweight_bones)  # + len(Bones.bone_list_parenting)

        # Get Double Entries
        print('DOUBLE ENTRIES:')
        print('RENAME:')
        list = []
        for key, value in temp_rename_bones.items():
            for name in value:
                if name.lower() not in list:
                    list.append(name.lower())
                else:
                    print(key + " | " + name)
        print('REWEIGHT:')
        list = []
        for key, value in temp_reweight_bones.items():
            for name in value:
                if name.lower() not in list:
                    list.append(name.lower())
                else:
                    print(key + " | " + name)
        print('DOUBLES END')

        # Check if model is mmd model
        mmd_root = None
        try:
            mmd_root = armature.parent.mmd_root
        except AttributeError:
            pass

        # Perform mmd specific operations
        if mmd_root:

            # Set correct mmd shading
            mmd_root.use_toon_texture = False
            mmd_root.use_sphere_texture = False

            # Convert mmd bone morphs into shape keys
            if len(mmd_root.bone_morphs) > 0:

                current_step = 0
                wm.progress_begin(current_step, len(mmd_root.bone_morphs))

                armature.data.pose_position = 'POSE'
                for index, morph in enumerate(mmd_root.bone_morphs):
                    current_step += 1
                    wm.progress_update(current_step)

                    armature.parent.mmd_root.active_morph = index
                    mmd_tools_local.operators.morph.ViewBoneMorph.execute(None, context)

                    mesh = tools.common.get_meshes_objects()[0]
                    tools.common.select(mesh)

                    mod = mesh.modifiers.new(morph.name, 'ARMATURE')
                    mod.object = armature
                    bpy.ops.object.modifier_apply(apply_as='SHAPE', modifier=mod.name)
                wm.progress_end()


        # Perform source engine specific operations
        # Check if model is source engine model
        source_engine = False
        for bone in armature.pose.bones:
            if bone.name.startswith('ValveBiped'):
                source_engine = True
                break

        # Remove unused animation data
        if armature.animation_data and armature.animation_data.action and armature.animation_data.action.name == 'ragdoll':
            armature.animation_data_clear()
            source_engine = True

        # Delete unused VTA mesh
        for mesh in tools.common.get_meshes_objects(mode=1):
            if mesh.name == 'VTA vertices':
                tools.common.delete_hierarchy(mesh)
                source_engine = True
                break

        if source_engine:
            # Delete unused physics meshes (like rigidbodies)
            for mesh in tools.common.get_meshes_objects():
                if mesh.name.endswith('_physics')\
                        or mesh.name.endswith('_lod1')\
                        or mesh.name.endswith('_lod2')\
                        or mesh.name.endswith('_lod3')\
                        or mesh.name.endswith('_lod4')\
                        or mesh.name.endswith('_lod5')\
                        or mesh.name.endswith('_lod6'):
                    tools.common.delete_hierarchy(mesh)

        # Reset to default
        tools.common.set_default_stage()

        # Set better bone view
        armature.data.draw_type = 'OCTAHEDRAL'
        armature.draw_type = 'WIRE'
        armature.show_x_ray = True
        armature.data.show_bone_custom_shapes = False
        armature.layers[0] = True

        # Disable backface culling
        if context.area:
            context.area.spaces[0].show_backface_culling = False

        # Remove Rigidbodies and joints
        for obj in bpy.data.objects:
            if 'rigidbodies' in obj.name or 'joints' in obj.name:
                tools.common.delete_hierarchy(obj)

        # Remove objects from  different layers and things that are not meshes
        for child in armature.children:
            for child2 in child.children:
                if not child2.layers[0] or child2.type != 'MESH':
                    tools.common.delete(child2)

            if not child.layers[0] or child.type != 'MESH':
                tools.common.delete(child)

        # Remove empty mmd object and unused objects
        tools.common.remove_empty()
        tools.common.remove_unused_objects()

        # Joins meshes into one and calls it 'Body'
        mesh = tools.common.join_meshes()
        # tools.common.select(armature)
        #
        # # Correct pivot position
        # try:
        #     # bpy.ops.view3d.snap_cursor_to_center()
        #     bpy.context.scene.cursor_location = (0.0, 0.0, 0.0)
        #     bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        # except RuntimeError:
        #     pass

        tools.common.unselect_all()
        tools.common.select(mesh)

        # # Correct pivot position
        # try:
        #     # bpy.ops.view3d.snap_cursor_to_center()
        #     bpy.context.scene.cursor_location = (0.0, 0.0, 0.0)
        #     bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
        # except RuntimeError:
        #     pass

        # Unlock all transforms
        for i in range(0, 3):
            armature.lock_location[i] = False
            armature.lock_rotation[i] = False
            armature.lock_scale[i] = False
            mesh.lock_location[i] = False
            mesh.lock_rotation[i] = False
            mesh.lock_scale[i] = False

        # Unlock all bone transforms
        for bone in armature.pose.bones:
            bone.lock_location[0] = False
            bone.lock_location[1] = False
            bone.lock_location[2] = False
            bone.lock_rotation[0] = False
            bone.lock_rotation[1] = False
            bone.lock_rotation[2] = False
            bone.lock_scale[0] = False
            bone.lock_scale[1] = False
            bone.lock_scale[2] = False

        if source_engine and tools.common.has_shapekeys(mesh):
            mesh.data.shape_keys.key_blocks[0].name = "Basis"

        # Remove empty shape keys and then save the shape key order
        tools.common.clean_shapekeys(mesh)
        tools.common.save_shapekey_order(mesh.name)

        # Combines same materials
        if context.scene.combine_mats:
            bpy.ops.combine.mats()
        else:
            # At least clean material names. Combining mats would do this otherwise
            tools.common.clean_material_names(mesh)

        # If all materials are transparent, make them visible. Also set transparency always to Z-Transparency
        all_transparent = True
        for mat_slot in mesh.material_slots:
            mat_slot.material.transparency_method = 'Z_TRANSPARENCY'
            if mat_slot.material.alpha > 0:
                all_transparent = False
        if all_transparent:
            for mat_slot in mesh.material_slots:
                mat_slot.material.alpha = 1

        # Reorders vrc shape keys to the correct order
        tools.common.sort_shape_keys(mesh.name)

        # Fix all shape key names of half jp chars
        if tools.common.has_shapekeys(mesh):
            for shapekey in mesh.data.shape_keys.key_blocks:
                shapekey.name = tools.translate.fix_jp_chars(shapekey.name)

        # Fix faulty UV coordinates
        fixed_uv_coords = 0
        for uv in mesh.data.uv_layers:
            for vert in range(len(uv.data) - 1):
                if math.isnan(uv.data[vert].uv.x):
                    uv.data[vert].uv.x = 0
                    fixed_uv_coords += 1
                if math.isnan(uv.data[vert].uv.y):
                    uv.data[vert].uv.y = 0
                    fixed_uv_coords += 1

        # Translate bones
        to_translate = []
        for bone in armature.data.bones:
            to_translate.append(bone.name)
        tools.translate.update_dictionary(to_translate)
        for bone in armature.data.bones:
            bone.name, translated = tools.translate.translate(bone.name)

        # Armature should be selected and in edit mode
        tools.common.unselect_all()
        tools.common.select(armature)
        tools.common.switch('EDIT')

        # Show all hidden verts and faces
        if bpy.ops.mesh.reveal.poll():
            bpy.ops.mesh.reveal()

        # Remove Bone Groups
        for group in armature.pose.bone_groups:
            armature.pose.bone_groups.remove(group)

        # Model should be in rest position
        armature.data.pose_position = 'REST'

        # Count steps for loading bar again and reset the layers
        steps += len(armature.data.edit_bones)
        for bone in armature.data.edit_bones:
            if bone.name in Bones.bone_list or bone.name.startswith(tuple(Bones.bone_list_with)):
                if bone.parent is not None:
                    steps += 1
                else:
                    steps -= 1
            bone.layers[0] = True

        # Start loading bar
        current_step = 0
        wm.progress_begin(current_step, steps)

        # List of chars to replace if they are at the start of a bone name
        starts_with = [
            ('_', ''),
            ('ValveBiped_', ''),
            ('Bip1_', 'Bip_'),
            ('Bip01_', 'Bip_'),
            ('Bip001_', 'Bip_'),
            ('Character1_', ''),
            ('HLP_', ''),
            ('JD_', ''),
            ('JU_', ''),
            ('Armature|', ''),
            ('Bone_', ''),
            ('C_', ''),
            ('Cf_S_', ''),
            ('Cf_J_', ''),
            ('G_', ''),
        ]

        # Standardize names
        for bone in armature.data.edit_bones:
            current_step += 1
            wm.progress_update(current_step)

            # Make all the underscores!
            name = bone.name.replace(' ', '_')\
                .replace('-', '_')\
                .replace('.', '_')\
                .replace('____', '_')\
                .replace('___', '_')\
                .replace('__', '_')\

            # Always uppercase at the start and after an underscore
            upper_name = ''
            for i, s in enumerate(name.split('_')):
                if i != 0:
                    upper_name += '_'
                upper_name += s[:1].upper() + s[1:]
            name = upper_name

            # Replace if name starts with specified chars
            for replacement in starts_with:
                if name.startswith(replacement[0]):
                    name = replacement[1] + name[len(replacement[0]):]

            # Remove digits from the start
            name_split = name.split('_')
            if len(name_split) > 1 and name_split[0].isdigit():
                name = name_split[1]

            # Specific condition
            name_split = name.split('"')
            if len(name_split) > 3:
                name = name_split[1]

            # Another specific condition
            if ':' in name:
                for i, split in enumerate(name.split(':')):
                    if i == 0:
                        name = ''
                    else:
                        name += split

            # Remove S0 from the end
            if name[-2:] == 'S0':
                name = name[:-2]

            bone.name = name

        # Add conflicting bone names to new list
        conflicting_bones = []
        for names in Bones.bone_list_conflicting_names:
            if '\Left' not in names[1] and '\L' not in names[1]:
                conflicting_bones.append(names)
                continue

            names0 = []
            name1 = ''
            name2 = ''
            for name0 in names[0]:
                names0.append(name0.replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l'))
            if '\Left' in names[1] or '\L' in names[1]:
                name1 = names[1].replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l')
            if '\Left' in names[2] or '\L' in names[2]:
                name2 = names[2].replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l')
            conflicting_bones.append((names0, name1, name2))

            for name0 in names[0]:
                names0.append(name0.replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r'))
            if '\Left' in names[1] or '\L' in names[1]:
                name1 = names[1].replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r')
            if '\Left' in names[2] or '\L' in names[2]:
                name2 = names[2].replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r')
            conflicting_bones.append((names0, name1, name2))

        # Resolve conflicting bone names
        for names in conflicting_bones:

            # Search for bone in armature
            bone = None
            for bone_tmp in armature.data.edit_bones:
                if bone_tmp.name.lower() == names[1].lower():
                    bone = bone_tmp
                    break

            # Cancel if bone was not found
            if not bone:
                continue

            # Search for all the required bones
            found_all = True
            for name in names[0]:
                found = False
                for bone_tmp in armature.data.edit_bones:
                    if bone_tmp.name.lower() == name.lower():
                        found = True
                        break
                if not found:
                    found_all = False
                    break

            # Rename only if all required bones are found
            if found_all:
                bone.name = names[2]

        # Standardize bone names again (new duplicate bones have ".001" in it)
        for bone in armature.data.edit_bones:
            bone.name = bone.name.replace('.', '_')

        # Rename all the bones
        spines = []
        spine_parts = []
        for bone_new, bones_old in temp_rename_bones.items():
            if '\Left' in bone_new or '\L' in bone_new:
                bones = [[bone_new.replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l'), ''],
                         [bone_new.replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r'), '']]
            else:
                bones = [[bone_new, '']]
            for bone_old in bones_old:
                if '\Left' in bone_new or '\L' in bone_new:
                    bones[0][1] = bone_old.replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l')
                    bones[1][1] = bone_old.replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r')
                else:
                    bones[0][1] = bone_old

                for bone in bones:  # bone[0] = new name, bone[1] = old name
                    current_step += 1
                    wm.progress_update(current_step)

                    # Seach for bone in armature
                    bone_final = None
                    for bone_tmp in armature.data.edit_bones:
                        if bone_tmp.name.lower() == bone[1].lower():
                            bone_final = bone_tmp
                            break

                    # Cancel if bone was not found
                    if not bone_final:
                        continue

                    # If spine bone, then don't rename for now, and ignore spines with no children
                    if bone_new == 'Spine':
                        if len(bone_final.children) > 0:
                            spines.append(bone_final.name)
                        else:
                            spine_parts.append(bone_final.name)
                        continue

                    # Rename the bone
                    if bone[0] not in armature.data.edit_bones:
                        bone_final.name = bone[0]

        # Add bones to parent reweight list
        for name in Bones.bone_reweigth_to_parent:
            if '\Left' in name or '\L' in name:
                bones = [name.replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l'),
                         name.replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r')]
            else:
                bones = [name]

            for bone_name in bones:
                # Search for bone in armature
                bone = None
                for bone_tmp in armature.data.edit_bones:
                    if bone_tmp.name.lower() == bone_name.lower():
                        bone = bone_tmp
                        break

                # Add bone to reweight list
                if bone and bone.parent:
                    temp_list_reweight_bones[bone.name] = bone.parent.name

        # Check if it is a mixamo model
        mixamo = False
        for bone in armature.data.edit_bones:
            if not mixamo and 'Mixamo' in bone.name:
                mixamo = True
                break

        # Rename bones which don't have a side and try to detect it automatically
        for key, value in Bones.bone_list_rename_unknown_side.items():
            for bone in armature.data.edit_bones:
                parent = bone.parent
                if parent is None:
                    continue
                if parent.name == key or parent.name == key.lower():
                    if 'right' in bone.name.lower():
                        parent.name = 'Right ' + value
                        break
                    elif 'left' in bone.name.lower():
                        parent.name = 'Left ' + value
                        break

                parent = parent.parent
                if parent is None:
                    continue
                if parent.name == key or parent.name == key.lower():
                    if 'right' in bone.name.lower():
                        parent.name = 'Right ' + value
                        break
                    elif 'left' in bone.name.lower():
                        parent.name = 'Left ' + value
                        break

        # Remove un-needed bones, disconnect them and set roll to 0
        for bone in armature.data.edit_bones:
            if bone.name in Bones.bone_list or bone.name.startswith(tuple(Bones.bone_list_with)):
                if bone.parent and mesh.vertex_groups.get(bone.name) and mesh.vertex_groups.get(bone.parent.name):
                    temp_list_reweight_bones[bone.name] = bone.parent.name
                else:
                    armature.data.edit_bones.remove(bone)
            else:
                bone.use_connect = False
                bone.roll = 0

        # Make Hips top parent and reparent other top bones to hips
        if 'Hips' in armature.data.edit_bones:
            hips = armature.data.edit_bones.get('Hips')
            hips.parent = None
            for bone in armature.data.edit_bones:
                if bone.parent is None:
                    bone.parent = hips

        # == FIXING OF SPECIAL BONE CASES ==

        # Fix all spines!
        spine_count = len(spines)

        # Fix spines from armatures with no upper body (like skirts)
        if len(spine_parts) == 1 and not armature.data.edit_bones.get('Neck'):
            if spine_count == 0:
                armature.data.edit_bones.get(spine_parts[0]).name = 'Spine'
            else:
                spines.append(spine_parts[0])

        if spine_count == 0:
            pass

        elif spine_count == 1:  # Create missing Chest
            print('BONE CREATION')
            spine = armature.data.edit_bones.get(spines[0])
            chest = armature.data.edit_bones.new('Chest')
            neck = armature.data.edit_bones.get('Neck')

            # Check for neck
            if neck:
                chest_top = neck.head
            else:
                chest_top = spine.tail

            # Correct the names
            spine.name = 'Spine'
            chest.name = 'Chest'

            # Set new Chest bone to new position
            chest.tail = chest_top
            chest.head = spine.head
            chest.head[z_cord] = spine.head[z_cord] + (chest_top[z_cord] - spine.head[z_cord]) / 2
            chest.head[y_cord] = spine.head[y_cord] + (chest_top[y_cord] - spine.head[y_cord]) / 2

            # Adjust spine bone position
            spine.tail = chest.head

            # Reparent bones to include new chest
            chest.parent = spine

            for bone in armature.data.edit_bones:
                if bone.parent == spine:
                    bone.parent = chest

        elif spine_count == 2:  # Everything correct, just rename them
            print('NORMAL')
            armature.data.edit_bones.get(spines[0]).name = 'Spine'
            armature.data.edit_bones.get(spines[1]).name = 'Chest'

        elif spine_count == 4 and source_engine:  # SOURCE ENGINE SPECIFIC
            print('SOURCE ENGINE')
            spine = armature.data.edit_bones.get(spines[0])
            chest = armature.data.edit_bones.get(spines[2])

            chest.name = 'Chest'
            spine.name = 'Spine'

            spine.tail = chest.head

            temp_list_reweight_bones[spines[1]] = 'Spine'
            temp_list_reweight_bones[spines[3]] = 'Chest'

        elif spine_count > 2:  # Merge spines
            print('MASS MERGING')
            print(spines)
            spine = armature.data.edit_bones.get(spines[0])
            chest = armature.data.edit_bones.get(spines[spine_count - 1])

            # Correct names
            spine.name = 'Spine'
            chest.name = 'Chest'

            # Adjust spine bone position
            spine.tail = chest.head

            # Add all redundant spines to the merge list
            for spine in spines[1:spine_count-1]:
                print(spine)
                temp_list_reweight_bones[spine] = 'Spine'

        # Fix missing neck
        if 'Neck' not in armature.data.edit_bones:
            if 'Chest' in armature.data.edit_bones:
                if 'Head' in armature.data.edit_bones:
                    neck = armature.data.edit_bones.new('Neck')
                    chest = armature.data.edit_bones.get('Chest')
                    head = armature.data.edit_bones.get('Head')
                    neck.head = chest.tail
                    neck.tail = head.head

                    if neck.head[z_cord] == neck.tail[z_cord]:
                        neck.tail[z_cord] += 0.1

        # Straighten up the head bone
        if 'Head' in armature.data.edit_bones:
            head = armature.data.edit_bones.get('Head')
            head.tail[x_cord] = head.head[x_cord]
            head.tail[y_cord] = head.head[y_cord]
            if head.tail[z_cord] < head.head[z_cord]:
                head.tail[z_cord] = head.head[z_cord] + 0.1

        # Correct arm bone positions for better looks
        tools.common.correct_bone_positions()

        # Hips bone should be fixed as per specification from the SDK code
        full_body_tracking = context.scene.full_body
        if not mixamo:
            if 'Hips' in armature.data.edit_bones:
                if 'Spine' in armature.data.edit_bones:
                    if 'Left leg' in armature.data.edit_bones:
                        if 'Right leg' in armature.data.edit_bones:
                            hips = armature.data.edit_bones.get('Hips')
                            spine = armature.data.edit_bones.get('Spine')
                            left_leg = armature.data.edit_bones.get('Left leg')
                            right_leg = armature.data.edit_bones.get('Right leg')
                            left_knee = armature.data.edit_bones.get('Left knee')
                            right_knee = armature.data.edit_bones.get('Right knee')

                            # Fixing the hips
                            if not full_body_tracking:

                                # Hips should have x value of 0 in both head and tail
                                middle_x = (right_leg.head[x_cord] + left_leg.head[x_cord]) / 2
                                hips.head[x_cord] = middle_x
                                hips.tail[x_cord] = middle_x

                                # Make sure the hips bone (tail and head tip) is aligned with the legs Y
                                hips.head[y_cord] = right_leg.head[y_cord]
                                hips.tail[y_cord] = right_leg.head[y_cord]

                                hips.head[z_cord] = right_leg.head[z_cord]
                                hips.tail[z_cord] = spine.head[z_cord]

                                if hips.tail[z_cord] < hips.head[z_cord]:
                                    hips.tail[z_cord] = hips.tail[z_cord] + 0.1

                                # if hips.tail[z_cord] < hips.head[z_cord]:
                                #     hips_height = hips.head[z_cord]
                                #     hips.head = hips.tail
                                #     hips.tail[z_cord] = hips_height
                                #
                                #
                                #
                                # hips_height = hips.head[z_cord]
                                # hips.head = hips.tail
                                # hips.tail[z_cord] = hips_height

                                # # Hips should have x value of 0 in both head and tail
                                # hips.head[x_cord] = 0
                                # hips.tail[x_cord] = 0

                                # # Make sure the hips bone (tail and head tip) is aligned with the legs Y
                                # hips.head[y_cord] = right_leg.head[y_cord]
                                # hips.tail[y_cord] = right_leg.head[y_cord]

                                # Flip the hips bone and make sure the hips bone is not below the legs bone
                                # hip_bone_length = abs(hips.tail[z_cord] - hips.head[z_cord])
                                # hips.head[z_cord] = right_leg.head[z_cord]
                                # hips.tail[z_cord] = hips.head[z_cord] + hip_bone_length

                                # hips.head[z_cord] = right_leg.head[z_cord]
                                # hips.tail[z_cord] = spine.head[z_cord]

                                # if hips.tail[z_cord] < hips.head[z_cord]:
                                #     hips.tail[z_cord] = hips.tail[z_cord] + 0.1

                            # elif spine and chest and neck and head:
                            #     bones = [hips, spine, chest, neck, head]
                            #     for bone in bones:
                            #         bone_length = abs(bone.tail[z_cord] - bone.head[z_cord])
                            #         bone.tail[x_cord] = bone.head[x_cord]
                            #         bone.tail[y_cord] = bone.head[y_cord]
                            #         bone.tail[z_cord] = bone.head[z_cord] + bone_length

                            else:
                                if left_leg and left_knee and right_leg and right_knee:
                                    hips.head[x_cord] = 0
                                    hips.tail[x_cord] = 0

                                    hips.tail[y_cord] = hips.head[y_cord]

                                    hips.head[z_cord] = spine.head[z_cord]
                                    hips.tail[z_cord] = right_leg.head[z_cord]

                                    left_leg_top = armature.data.edit_bones.new('Left leg top')
                                    right_leg_top = armature.data.edit_bones.new('Right leg top')

                                    left_leg_top.head = left_leg.head
                                    left_leg_top.tail = left_leg.head
                                    left_leg_top.tail[z_cord] = left_leg.head[z_cord] + 0.1

                                    right_leg_top.head = right_leg.head
                                    right_leg_top.tail = right_leg.head
                                    right_leg_top.tail[z_cord] = right_leg.head[z_cord] + 0.1

                                    spine.head = hips.head
                                    # hips.head[z_cord] -= 0.0025
                                    # spine.head[z_cord] += 0.0025

                                    left_leg.name = "Left leg 2"
                                    right_leg.name = "Right leg 2"

                                    left_leg_top.name = "Left leg"
                                    right_leg_top.name = "Right leg"

                                    left_leg_top.parent = hips
                                    right_leg_top.parent = hips

                                    left_leg.parent = left_leg_top
                                    right_leg.parent = right_leg_top

                                    left_knee.parent = left_leg_top
                                    right_knee.parent = right_leg_top

                            # # Fixing legs
                            # right_knee = armature.data.edit_bones.get('Right knee')
                            # left_knee = armature.data.edit_bones.get('Left knee')
                            # if right_knee and left_knee:
                            #     # Make sure the upper legs tail are the same x/y values as the lower leg tail x/y
                            #     right_leg.tail[x_cord] = right_leg.head[x_cord]
                            #     left_leg.tail[x_cord] = left_knee.head[x_cord]
                            #     right_leg.head[y_cord] = right_knee.head[y_cord]
                            #     left_leg.head[y_cord] = left_knee.head[y_cord]
                            #
                            #     # Make sure the leg bones are setup straight. (head should be same X as tail)
                            #     left_leg.head[x_cord] = left_leg.tail[x_cord]
                            #     right_leg.head[x_cord] = right_leg.tail[x_cord]
                            #
                            #     # Make sure the left legs (head tip) have the same Y values as right leg (head tip)
                            #     left_leg.head[y_cord] = right_leg.head[y_cord]

        # Function: Reweight all eye children into the eyes
        def add_eye_children(eye_bone, parent_name):
            for eye in eye_bone.children:
                temp_list_reweight_bones[eye.name] = parent_name
                add_eye_children(eye, parent_name)

        # Reweight all eye children into the eyes
        for eye_name in ['Eye_L', 'Eye_R']:
            if eye_name in armature.data.edit_bones:
                eye = armature.data.edit_bones.get(eye_name)
                add_eye_children(eye, eye.name)

        # Rotate if on head and not fbx (Unreal engine model)
        if 'Hips' in armature.data.edit_bones:

            hips = armature.pose.bones.get('Hips')

            obj = hips.id_data
            matrix_final = obj.matrix_world * hips.matrix
            # print(matrix_final)
            # print(matrix_final[2][3])
            # print(fbx)

            if not fbx and matrix_final[2][3] < 0:
                # print(hips.head[0], hips.head[1], hips.head[2])
                # Rotation of -180 around the X-axis
                rot_x_neg180 = Matrix.Rotation(-math.pi, 4, 'X')
                armature.matrix_world = rot_x_neg180 * armature.matrix_world

                mesh.rotation_euler = (math.radians(180), 0, 0)

        # Fixes bones disappearing, prevents bones from having their tail and head at the exact same position
        for bone in armature.data.edit_bones:
            if round(bone.head[x_cord], 5) == round(bone.tail[x_cord], 5)\
                    and round(bone.head[y_cord], 5) == round(bone.tail[y_cord], 5)\
                    and round(bone.head[z_cord], 5) == round(bone.tail[z_cord], 5):
                if bone.name == 'Hips' and full_body_tracking:
                    bone.tail[z_cord] -= 0.1
                else:
                    bone.tail[z_cord] += 0.1

        # Mixing the weights
        tools.common.unselect_all()
        tools.common.switch('OBJECT')
        tools.common.select(mesh)

        # for bone_name in temp_rename_bones.keys():
        #     bone = armature.data.bones.get(bone_name)
        #     if bone:
        #         print(bone_name)
        #         bone.hide = False

        for bone_new, bones_old in temp_reweight_bones.items():
            if '\Left' in bone_new or '\L' in bone_new:
                bones = [[bone_new.replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l'), ''],
                         [bone_new.replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r'), '']]
            else:
                bones = [[bone_new, '']]
            for bone_old in bones_old:
                if '\Left' in bone_new or '\L' in bone_new:
                    bones[0][1] = bone_old.replace('\Left', 'Left').replace('\left', 'left').replace('\L', 'L').replace('\l', 'l')
                    bones[1][1] = bone_old.replace('\Left', 'Right').replace('\left', 'right').replace('\L', 'R').replace('\l', 'r')
                else:
                    bones[0][1] = bone_old

                for bone in bones:  # bone[0] = new name, bone[1] = old name
                    current_step += 1
                    wm.progress_update(current_step)

                    # Seach for vertex group
                    vg = None
                    for vg_tmp in mesh.vertex_groups:
                        if vg_tmp.name.lower() == bone[1].lower():
                            vg = vg_tmp
                            break

                    # Cancel if vertex group was not found
                    if not vg:
                        continue

                    if bone[0] == vg.name:
                        print('BUG: ' + bone[0] + ' tried to mix weights with itself!')
                        continue

                    # print(bone[1] + " to1 " + bone[0])

                    # If important vertex group is not there create it
                    if mesh.vertex_groups.get(bone[0]) is None:
                        if bone[0] in Bones.dont_delete_these_bones and bone[0] in armature.data.bones:
                            bpy.ops.object.vertex_group_add()
                            mesh.vertex_groups.active.name = bone[0]
                            if mesh.vertex_groups.get(bone[0]) is None:
                                continue
                        else:
                            continue

                    bone_tmp = armature.data.bones.get(vg.name)
                    if bone_tmp:
                        for child in bone_tmp.children:
                            if not temp_list_reparent_bones.get(child.name):
                                temp_list_reparent_bones[child.name] = bone[0]

                    # print(bone[1] + " to " + bone[0])
                    tools.common.mix_weights(mesh, vg.name, bone[0])

        # Old mixing weights. Still important
        for key, value in temp_list_reweight_bones.items():
            current_step += 1
            wm.progress_update(current_step)

            # Search for vertex groups
            vg_from = None
            vg_to = None
            for vg_tmp in mesh.vertex_groups:
                if vg_tmp.name.lower() == key.lower():
                    vg_from = vg_tmp
                    if vg_to:
                        break
                elif vg_tmp.name.lower() == value.lower():
                    vg_to = vg_tmp
                    if vg_from:
                        break

            # Cancel if vertex groups was not found
            if not vg_from or not vg_to:
                continue

            bone_tmp = armature.data.bones.get(vg_from.name)
            if bone_tmp:
                for child in bone_tmp.children:
                    if not temp_list_reparent_bones.get(child.name):
                        temp_list_reparent_bones[child.name] = vg_to.name

            if vg_from.name == vg_to.name:
                print('BUG: ' + vg_to.name + ' tried to mix weights with itself!')
                continue

            # Mix the weights
            # print(vg_from.name, 'into', vg_to.name)
            tools.common.mix_weights(mesh, vg_from.name, vg_to.name)

        tools.common.unselect_all()
        tools.common.select(armature)
        tools.common.switch('EDIT')

        # Reparent all bones to be correct for unity mapping and vrc itself
        for key, value in temp_list_reparent_bones.items():
            # current_step += 1
            # wm.progress_update(current_step)
            if key in armature.data.edit_bones and value in armature.data.edit_bones:
                armature.data.edit_bones.get(key).parent = armature.data.edit_bones.get(value)

        # Bone constraints should be deleted
        # if context.scene.remove_constraints:
        tools.common.delete_bone_constraints()

        # Removes unused vertex groups
        tools.common.remove_unused_vertex_groups()

        # Zero weight bones should be deleted
        if context.scene.remove_zero_weight:
            tools.common.delete_zero_weight()

        # # This is code for testing
        # print('LOOKING FOR BONES!')
        # if 'Head' in tools.common.get_armature().pose.bones:
        #     print('THEY ARE THERE!')
        # else:
        #     print('NOT FOUND!!!!!!')
        # return {'FINISHED'}

        # At this point, everything should be fixed and now we validate and give errors if needed

        # The bone hierarchy needs to be validated
        hierarchy_check_hips = check_hierarchy(False, [
            ['Hips', 'Spine', 'Chest', 'Neck', 'Head'],
            ['Hips', 'Left leg', 'Left knee', 'Left ankle'],
            ['Hips', 'Right leg', 'Right knee', 'Right ankle'],
            ['Chest', 'Left shoulder', 'Left arm', 'Left elbow', 'Left wrist'],
            ['Chest', 'Right shoulder', 'Right arm', 'Right elbow', 'Right wrist']
        ])

        # Armature should be named correctly (has to be at the end because of multiple armatures)
        tools.common.fix_armature_names()

        # Fix shading (check for runtime error because of ci tests)
        if not source_engine:
            try:
                bpy.ops.mmd_tools.set_shadeless_glsl_shading()
            except RuntimeError:
                pass

        wm.progress_end()

        if not hierarchy_check_hips['result']:
            self.report({'ERROR'}, hierarchy_check_hips['message'])
            return {'FINISHED'}

        if fixed_uv_coords:
            tools.common.show_error(6.2, ['The model was successfully fixed, but there were ' + str(fixed_uv_coords) + ' faulty UV coordinates.',
                                          'This could result in broken textures and you might have to fix them manually.',
                                          'This issue is often caused by edits in PMX editor.'])
            return {'FINISHED'}

        self.report({'INFO'}, 'Model successfully fixed.')
        return {'FINISHED'}


def check_hierarchy(check_parenting, correct_hierarchy_array):
    armature = tools.common.set_default_stage()

    missing_bones = []
    missing2 = ['The following bones were not found:', '']

    for correct_hierarchy in correct_hierarchy_array:  # For each hierarchy array
        line = ' - '

        for index, bone in enumerate(correct_hierarchy):  # For each hierarchy bone item
            if bone not in missing_bones and bone not in armature.data.bones:
                missing_bones.append(bone)
                if len(line) > 3:
                    line += ', '
                line += bone

        if len(line) > 3:
            missing2.append(line)

    if len(missing2) > 2 and not check_parenting:
        missing2.append('')
        missing2.append('Looks like you found a model which Cats could not fix!')
        missing2.append('If this is a non modified model we would love to make it compatible.')
        missing2.append('Report it to us in the forum or in our discord, links can be found in the Credits panel.')

        tools.common.show_error(6.4, missing2)
        return {'result': True, 'message': ''}

    if check_parenting:
        for correct_hierarchy in correct_hierarchy_array:  # For each hierachy array
            previous = None
            for index, bone in enumerate(correct_hierarchy):  # For each hierarchy bone item
                if index > 0:
                    previous = correct_hierarchy[index - 1]

                if bone in armature.data.bones:
                    bone = armature.data.bones[bone]

                    # If a previous item was found
                    if previous is not None:
                        # And there is no parent, then we have a problem mkay
                        if bone.parent is None:
                            return {'result': False, 'message': bone.name + ' is not parented at all, this will cause problems!'}
                        # Previous needs to be the parent of the current item
                        if previous != bone.parent.name:
                            return {'result': False, 'message': bone.name + ' is not parented to ' + previous + ', this will cause problems!'}

    return {'result': True}


class ModelSettings(bpy.types.Operator):
    bl_idname = "armature.settings"
    bl_label = "Fix Model Settings"

    def execute(self, context):
        return {'FINISHED'}

    def invoke(self, context, event):
        dpi_value = bpy.context.user_preferences.system.dpi
        return context.window_manager.invoke_props_dialog(self, width=dpi_value * 3.25, height=-550)

    def check(self, context):
        # Important for changing options
        return True

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)

        row = col.row(align=True)
        row.prop(context.scene, 'full_body')
        row = col.row(align=True)
        row.active = context.scene.remove_zero_weight
        row.prop(context.scene, 'keep_end_bones')
        row = col.row(align=True)
        row.prop(context.scene, 'combine_mats')
        row = col.row(align=True)
        row.prop(context.scene, 'remove_zero_weight')

        if context.scene.full_body:
            col.separator()
            row = col.row(align=True)
            row.scale_y = 0.7
            row.label('INFO:', icon='INFO')
            row = col.row(align=True)
            row.scale_y = 0.7
            row.label('You can safely ignore the', icon_value=tools.supporter.preview_collections["custom_icons"]["empty"].icon_id)
            row = col.row(align=True)
            row.scale_y = 0.7
            row.label('"Spine length zero" warning in Unity.', icon_value=tools.supporter.preview_collections["custom_icons"]["empty"].icon_id)
            col.separator()
