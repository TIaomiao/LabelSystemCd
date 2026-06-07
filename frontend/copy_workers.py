import shutil
import os
import glob

source_dir = "/home/Larry/code/Ziqiu/LabelSystem/frontend/node_modules/cornerstone-wado-image-loader/dist/dynamic-import"
dest_dir = "/home/Larry/code/Ziqiu/LabelSystem/frontend/public/cwil"

if not os.path.exists(dest_dir):
    os.makedirs(dest_dir)

files = glob.glob(os.path.join(source_dir, "*"))
print(f"Copying {len(files)} files...")
for f in files:
    shutil.copy(f, dest_dir)
    print(f"Copied {os.path.basename(f)}")

print("Done.")
