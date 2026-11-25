import tomllib

from common import OVERRIDES_DIR as out_dir
from common import UNPACKED_DIR as unpacked

def replace_checked(text, replacements, label):
    for old, new in replacements:
        cnt = text.count(old)
        assert cnt >= 1, f"{label}: missing expected literal: {old!r}"
        text = text.replace(old, new)
    return text

# 1. shop.toml
shop_src = (unpacked / "shop.toml").read_text("utf-8")
shop_repl = [
    # Sections (MUST match 0x14156b020 in dirttown.exe!)
    ('section = "Loaders"', 'section = "Погрузчики"'),
    ('section = "Earthmoving"', 'section = "Землеройные"'),
    ('section = "Haulage"', 'section = "Самосвалы"'),
    ('section = "Farm"', 'section = "Фермерские"'),
    ('section = "Getting about"', 'section = "Транспорт"'),
    # Names
    ('name = "Wheel loader"', 'name = "Фронтальный погрузчик"'),
    ('name = "Large wheel loader"', 'name = "Большой погрузчик"'),
    ('name = "Crawler dozer"', 'name = "Гусеничный бульдозер"'),
    ('name = "Excavator"', 'name = "Экскаватор"'),
    ('name = "Articulated hauler"', 'name = "Шарнирный самосвал"'),
    ('name = "Hooklift truck"', 'name = "Самосвал с мультилифтом"'),
    ('name = "Farm tractor"', 'name = "Трактор"'),
    ('name = "Pickup"', 'name = "Пикап"'),
    ('name = "Tracked carrier"', 'name = "Гусеничный вездеход"'),
    ('name = "Snowmobile"', 'name = "Снегоход"'),
    ('name = "Dirt bike"', 'name = "Кроссовый мотоцикл"'),
    # Specs
    ('spec = "1.8 m3 bucket"', 'spec = "ковш 1,8 м³"'),
    ('spec = "3.8 m3 bucket"', 'spec = "ковш 3,8 м³"'),
    ('spec = "3.4 m blade"', 'spec = "отвал 3,4 м"'),
    ('spec = "6.6 m reach"', 'spec = "вылет 6,6 м"'),
    ('spec = "12 m3 body"', 'spec = "кузов 12 м³"'),
    ('spec = "takes every container"', 'spec = "любые контейнеры"'),
    ('spec = "front loader, three point hitch"', 'spec = "ковш спереди, трёхточечная навеска"'),
    ('spec = "plough mount"', 'spec = "крепление под отвал"'),
    ('spec = "two bodies, it swims"', 'spec = "две секции, плавает"'),
    ('spec = "one seat, one ski each side"', 'spec = "одно место, лыжи по бокам"'),
    ('spec = "two wheels, no excuses"', 'spec = "два колеса, без отговорок"'),
    # Taglines
    ('tagline = "The site\'s all-rounder: scoops, carries, ploughs and loads a truck in four passes."',
     'tagline = "Универсал на объекте: черпает, возит, чистит снег и грузит самосвал за четыре захода."'),
    ('tagline = "Twice the bucket, a pin hitch for trailers, and a cab you could live in."',
     'tagline = "Ковш вдвое больше, буксирная серьга для прицепов и кабина, в которой хоть живи."'),
    ('tagline = "Push, rip and grade. Tracks that float on mud and a blade that tilts as you think it."',
     'tagline = "Толкай, рыхли, планируй. Гусеницы не вязнут в грязи, а отвал послушен каждому движению."'),
    ('tagline = "A trench by lunch, a pond by tea. Quick coupler ready."',
     'tagline = "Траншея к обеду, пруд к чаю. Оснащён быстросъёмом."'),
    ('tagline = "Six wheels driven, a body that tips in eight seconds and a ride over anything."',
     'tagline = "Полный привод на шесть колёс, разгрузка за восемь секунд и проходимость везде."'),
    ('tagline = "Swap a tipper for a flatrack without leaving the seat."',
     'tagline = "Меняй самосвальный кузов на платформу, не выходя из кабины."'),
    ('tagline = "Loader up front, plough behind, and the radio still works."',
     'tagline = "Спереди погрузчик, сзади плуг — и радио всё ещё ловит."'),
    ('tagline = "The boss\'s ride, the plough\'s mount, the coffee run."',
     'tagline = "Машина начальника, крепление под отвал и верный транспорт за кофе."'),
    ('tagline = "Two bodies, four tracks, and it floats when the creek is higher than you thought."',
     'tagline = "Две секции, четыре гусеницы — не утонет, даже если ручей разлился глубже ожидаемого."'),
    ('tagline = "For the morning round of the village and nothing heavier."',
     'tagline = "Для утреннего объезда деревни — не для тяжёлых грузов."'),
    ('tagline = "Kick it, ride it, drop it in the ditch. It doesn\'t mind."',
     'tagline = "Завёл, погнал, уронил в канаву — ему всё нипочём."'),
]
shop_dst = replace_checked(shop_src, shop_repl, "shop.toml")
(out_dir / "shop.toml").parent.mkdir(parents=True, exist_ok=True)
(out_dir / "shop.toml").write_text(shop_dst, encoding="utf-8")
tomllib.loads(shop_dst)

# 2. key_layouts.toml (ONLY name & hint! Keep keybind parser expressions untouched)
kl_src = (unpacked / "key_layouts.toml").read_text("utf-8")
kl_repl = [
    ('name = "classic"', 'name = "Классическая"'),
    ('hint = "the arrows work the arm and the bucket, the left and right buttons curl, the mouse always looks"',
     'hint = "стрелки управляют стрелой и ковшом, ЛКМ и ПКМ — наклон ковша, мышь всегда вращает камеру"'),
    ('name = "farm sim"', 'name = "Как в Farm Sim"'),
    ('hint = "hold the left button and move the mouse for the arm and the bucket or the blade, the right for the excavator\'s stick and swing"',
     'hint = "зажмите ЛКМ и двигайте мышью для управления стрелой и ковшом/отвалом, ПКМ — рукоять и поворот экскаватора"'),
]
kl_dst = replace_checked(kl_src, kl_repl, "key_layouts.toml")
(out_dir / "key_layouts.toml").write_text(kl_dst, encoding="utf-8")
tomllib.loads(kl_dst)

# 3. pad_layouts.toml (ONLY name & hint! Keep pad binding parser expressions untouched)
pl_src = (unpacked / "pad_layouts.toml").read_text("utf-8")
pl_repl = [
    ('name = "hold LB"', 'name = "Удержание LB"'),
    ('hint = "hold LB and the right stick works the arm, the bucket or the blade"',
     'hint = "зажмите LB, чтобы правым стиком управлять стрелой, ковшом или отвалом"'),
    ('name = "click RS"', 'name = "Нажатие RS"'),
    ('hint = "click the right stick to switch it between the camera and the arm, the bucket or the blade"',
     'hint = "нажмите на правый стик для переключения между камерой и управлением стрелой, ковшом или отвалом"'),
    ('name = "classic"', 'name = "Классическая"'),
    ('hint = "the arm on the triggers and the bucket and the blade\'s tilt on the shoulders, the left stick driving"',
     'hint = "стрела на курках, ковш и наклон отвала на бамперах, левый стик — движение"'),
]
pl_dst = replace_checked(pl_src, pl_repl, "pad_layouts.toml")
(out_dir / "pad_layouts.toml").write_text(pl_dst, encoding="utf-8")
tomllib.loads(pl_dst)

# 4. sites/demo2/demo2.toml
demo_src = (unpacked / "sites" / "demo2" / "demo2.toml").read_text("utf-8")
demo_repl = [
    ('name = "Flower Hill"', 'name = "Цветочный холм"'),
    ('byline = "Demo map"', 'byline = "Демо-карта"'),
    ('accepts = ["27d9a082d2382faa"]', 'accepts = ["27d9a082d2382faa", "811034dce06dee68", "bc57be2314fd0a38"]'),
    ('locked = "Waiting for parts, estimated arrival dec 4th"',
     'locked = "Ожидаются запчасти, прибытие ориентировочно 4 дек."'),
    ('title = "Sand haul & more"', 'title = "Перевозка песка и не только"'),
    ('done = "40 tonnes in, the river jumped and the boulder on the hill. Score. Keep hauling if you feel like it"',
     'done = "40 тонн доставлено, река перепрыгнута, валун на холме. Отлично! Можете возить дальше, если хочется"'),
    ('sheet = "Sand to the gravel pad, {}"', 'sheet = "Песок на гравийную площадку, {}"'),
    ('bill = "Sand to the gravel pad"', 'bill = "Доставка песка на гравийную площадку"'),
    ('sheet = "Find the truck"', 'sheet = "Найдите пикап"'),
    ('bill = "Find the truck"', 'bill = "Поиск пикапа"'),
    ('sheet = "Jump the river with the truck"', 'sheet = "Перепрыгните реку на пикапе"'),
    ('bill = "Sick jump with the truck"', 'bill = "Эффектный прыжок на пикапе"'),
    ('say = "And when you are done, there is a truck up on the hill. Find it, and get it over the river. Somehow"',
     'say = "А когда закончите — наверху на холме стоит пикап. Найдите его и переправьте через реку. Хоть как-нибудь"'),
    ('sheet = "Get the boulder up on the hill"', 'sheet = "Затащите валун на холм"'),
    ('bill = "Boulder on hill"', 'bill = "Подъём валуна на холм"'),
    ('text = "Here is the start area with your machines."',
     'text = "Это стартовая площадка с вашей техникой."'),
    ('text = "There is sand on the far end of this site, and we need it."',
     'text = "На дальнем краю участка есть песок — он нам нужен."'),
    ('text = "Get at least 40 tonnes of sand to the gravel pad, for a well paying customer. This is quality sand"',
     'text = "Доставьте минимум 40 тонн песка на гравийную площадку для щедрого заказчика. Это отборный песок."'),
]
demo_dst = replace_checked(demo_src, demo_repl, "demo2.toml")
(out_dir / "sites" / "demo2").mkdir(parents=True, exist_ok=True)
(out_dir / "sites" / "demo2" / "demo2.toml").write_text(demo_dst, encoding="utf-8")
parsed_demo = tomllib.loads(demo_dst)
assert parsed_demo["name"] == "Цветочный холм"
assert parsed_demo["site"]["byline"] == "Демо-карта"
assert parsed_demo["mission"]["title"] == "Перевозка песка и не только"
print("All 4 TOML files translated & validated via tomllib cleanly!")
