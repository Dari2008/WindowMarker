from PIL import Image

img = Image.open("../public/images/haus1._annotated.png")

greenImage = Image.new("RGBA", img.size)
redImage = Image.new("RGBA", img.size)

def isCloseTo(color: tuple[int, int, int], comp: tuple[int, int, int], tol: float = 0.3):
    max_channel_diff = max(abs(c - o) for c, o in zip(color, comp))
    return max_channel_diff <= tol * 255
    

for x in range(img.width):
    for y in range(img.height):
        color = img.getpixel((x,y))
        if(isCloseTo(color, (0, 255, 0))):
            greenImage.putpixel((x, y), (255, 0, 0, 255))
        else:
            greenImage.putpixel((x, y), (0, 0, 0, 0))
            
        if(isCloseTo(color, (255, 0, 0))):
            redImage.putpixel((x, y), (255, 0, 0, 255))
        else:
            redImage.putpixel((x, y), (0, 0, 0, 0))
            
greenImage.save("./greenImage.png")
redImage.save("./redImage.png")