from PIL import Image

# Convert PNG to ICO
img = Image.open('leetcode_icon.png')
icon_sizes = [(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)]
img.save('leetcode-icon.ico', sizes=icon_sizes)
