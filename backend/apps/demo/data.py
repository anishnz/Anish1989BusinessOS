"""
Made-up data for "Install test data" (task 1.18, D-126).

Six test businesses with Nepali names (one for each pilot type), all at the
address the platform owner asked for: 2 White Street, Auckland City,
Auckland 1010, New Zealand. Customer emails use example.com (a name that can
never receive email). Nothing here belongs to a real person or business.
"""
from decimal import Decimal as D

EMAIL_DOMAIN = "anish1989.com.np"
ADDRESS = {"address": "2 White Street", "suburb": "Auckland City", "city": "Auckland", "postcode": "1010", "country": "New Zealand"}
FULL_ADDRESS = "2 White Street, Auckland City, Auckland 1010, New Zealand"


def role_email(role_slug: str) -> str:
    """roleas<role>@anish1989.com.np, for example roleasshopstaff@anish1989.com.np."""
    return f"roleas{role_slug.replace('_', '')}@{EMAIL_DOMAIN}"


# (first names, family name). Rotated per business so each business has different people.
PEOPLE = [
    ("Ram Bahadur", "Thapa"), ("Sita Kumari", "Sharma"), ("Hari Prasad", "Adhikari"), ("Gita", "Gurung"), ("Bikash", "Shrestha"),
    ("Sunita", "Rai"), ("Prakash", "Karki"), ("Anjali", "Magar"), ("Rajesh", "Poudel"), ("Kabita", "Tamang"),
    ("Suman", "Basnet"), ("Pooja", "Khadka"), ("Dipesh", "Bhandari"), ("Nirmala", "Lama"), ("Sanjay", "Maharjan"),
    ("Rina", "Thapa Magar"), ("Bishal", "Koirala"), ("Manisha", "Pandey"), ("Arjun", "Bista"), ("Sarita", "Ghimire"),
    ("Nabin", "Dahal"), ("Laxmi", "Bhattarai"), ("Kiran", "Joshi"), ("Puja", "Dhakal"), ("Ramesh", "Giri"),
    ("Samjhana", "Karki"), ("Binod", "Rana"), ("Kamala", "Neupane"), ("Sudip", "Acharya"), ("Asmita", "Pokharel"),
]

CUSTOMERS = [
    ("Bishnu Prasad", "Adhikari"), ("Durga", "Thapa"), ("Krishna", "Shrestha"), ("Saraswati", "Gurung"), ("Ganesh", "Tamang"),
    ("Parbati", "Rai"), ("Shyam", "Karki"), ("Radha", "Bhattarai"), ("Mohan", "Maharjan"), ("Sabina", "Lama"),
    ("Dinesh", "Khadka"), ("Usha", "Pokharel"), ("Bhim", "Bahadur KC"), ("Januka", "Dahal"), ("Pemba", "Sherpa"),
    ("Tara", "Joshi"),
]
CUSTOMER_TAGS = ["regular", "regular, wholesale", "halal", "festival orders", "new", "regular, Dashain", "", "office lunch"]
CUSTOMER_NOTES = [
    "Prefers pickup after 5 pm.", "Ring the bell, flat upstairs.", "Likes the meat cut small for curry.", "Orders every Friday.",
    "Pays by bank transfer.", "Ask about spice level.", "", "Allergic to peanuts (tell the kitchen).",
]

BUSINESSES = [
    {
        "slug": "test_butchery", "name": "Kathmandu Khasi Pasal", "industry": "butchery", "type": "Butchery",
        "categories": ["Khasi (goat)", "Kukhura (chicken)", "Lamb", "Pork and buff", "Ready to cook"],
        "products": [
            # name, category, unit, price, cost, min, step, search terms, description
            ("Khasi curry cut", 0, "kg", D("23.00"), D("15.50"), D("0.5"), D("0.5"), "goat curry cut, khasi ko masu, bakhra", "Fresh goat with bone, cut for curry."),
            ("Khasi leg (whole)", 0, "kg", D("26.50"), D("18.00"), D("1"), D("0.5"), "goat leg, khasi ko khutta", "Whole leg, about 2 to 3 kg."),
            ("Chicken curry cut", 1, "kg", D("12.90"), D("8.20"), D("0.5"), D("0.5"), "kukhura ko masu, chicken masu", "Skin off, cut small."),
            ("Chicken drumsticks", 1, "kg", D("10.50"), D("6.90"), D("0.5"), D("0.5"), "drumstick, khutta", ""),
            ("Lamb chops", 2, "kg", D("29.00"), D("21.00"), D("0.5"), D("0.5"), "lamb chop, bheda", "Trimmed loin chops."),
            ("Buff mince", 3, "kg", D("18.50"), D("12.00"), D("0.5"), D("0.5"), "buff keema, rango", "For momo and sekuwa."),
            ("Pork belly", 3, "kg", D("19.90"), D("13.50"), D("0.5"), D("0.5"), "bangur, pork", ""),
            ("Chicken sekuwa (marinated)", 4, "pack", D("14.00"), D("8.00"), D("1"), D("1"), "sekuwa, bbq", "500 g pack, Nepali spices."),
            ("Sukuti (dried meat) 250 g", 4, "pack", D("16.00"), D("9.50"), D("1"), D("1"), "sukuti, dried buff", ""),
            ("Chicken momo filling", 4, "pack", D("9.50"), D("5.20"), D("1"), D("1"), "momo masu", "Ready mixed, 1 kg."),
        ],
        # Stock (task 2.2): product number -> (received before the orders, warn at). After the orders, "low" is
        # counted down to its warning level and "out" is counted as 0, so the dashboard shows both.
        "stock": {0: (D("40"), D("8")), 1: (D("25"), D("5")), 2: (D("40"), D("8")), 3: (D("30"), D("6")), 4: (D("20"), D("5")),
                  5: (D("35"), D("8")), 6: (D("25"), D("5")), 7: (D("60"), D("10")), 8: (D("50"), D("10"))},
        "stock_low": 4, "stock_out": 8,
    },
    {
        "slug": "test_restaurant", "name": "Thamel Momo Ghar", "industry": "restaurant", "type": "Restaurant",
        "categories": ["Momo", "Noodles and soup", "Thali", "Snacks", "Drinks"],
        "products": [
            ("Chicken momo (10 pieces)", 0, "each", D("15.00"), D("5.50"), D("1"), D("1"), "kukhura momo, chicken dumpling", "Steamed, with tomato achar."),
            ("Buff momo (10 pieces)", 0, "each", D("16.00"), D("6.00"), D("1"), D("1"), "buff momo", ""),
            ("Veg momo (10 pieces)", 0, "each", D("13.00"), D("4.00"), D("1"), D("1"), "veg momo, tarkari momo", "Cabbage, paneer and onion."),
            ("Jhol momo", 0, "each", D("17.00"), D("6.50"), D("1"), D("1"), "jhol, soup momo", "In sesame and tomato soup."),
            ("Chicken thukpa", 1, "each", D("16.50"), D("5.80"), D("1"), D("1"), "thukpa, noodle soup", ""),
            ("Chicken chowmein", 1, "each", D("15.50"), D("5.00"), D("1"), D("1"), "chowmein, chau chau", ""),
            ("Dal bhat set", 2, "each", D("19.90"), D("7.50"), D("1"), D("1"), "dal bhat, khana, thali", "Rice, dal, tarkari, achar and meat curry."),
            ("Sel roti (3 pieces)", 3, "each", D("7.00"), D("1.80"), D("1"), D("1"), "sel roti, selroti", ""),
            ("Masala chiya", 4, "each", D("4.50"), D("0.90"), D("1"), D("1"), "chiya, tea, masala tea", ""),
            ("Mango lassi", 4, "each", D("6.00"), D("1.50"), D("1"), D("1"), "lassi", ""),
        ],
        "stock": {0: (D("80"), D("15")), 1: (D("60"), D("15")), 2: (D("60"), D("10")), 7: (D("40"), D("10"))},
        "stock_low": 1, "stock_out": 7,
    },
    {
        "slug": "test_catering", "name": "Himalayan Bhoj Catering", "industry": "catering", "type": "Catering",
        "categories": ["Buffet (per person)", "Platters", "Desserts", "Staff and hire"],
        "products": [
            ("Dal bhat buffet (per person)", 0, "each", D("28.00"), D("11.00"), D("20"), D("1"), "bhoj, buffet, khana", "Minimum 20 people."),
            ("Newari khaja set (per person)", 0, "each", D("25.00"), D("9.50"), D("20"), D("1"), "newari khaja, samay baji", ""),
            ("Momo platter (50 pieces)", 1, "pack", D("75.00"), D("28.00"), D("1"), D("1"), "momo platter", "Chicken or veg."),
            ("Sekuwa platter", 1, "pack", D("85.00"), D("35.00"), D("1"), D("1"), "sekuwa", "For 10 people."),
            ("Kheer tray", 2, "pack", D("45.00"), D("12.00"), D("1"), D("1"), "kheer, rice pudding", "For 20 people."),
            ("Jeri and swari", 2, "pack", D("55.00"), D("18.00"), D("1"), D("1"), "jeri, swari, jalebi", ""),
            ("Serving staff (per hour)", 3, "each", D("45.00"), D("30.00"), D("2"), D("1"), "waiter, staff", "Minimum 2 hours."),
        ],
        "stock": {2: (D("40"), D("5")), 3: (D("40"), D("5")), 4: (D("30"), D("4"))},
        "stock_low": 3, "stock_out": 4,
    },
    {
        "slug": "test_events", "name": "Basantapur Utsav Events", "industry": "events", "type": "Events",
        "categories": ["Venue", "Decoration", "Music and photos"],
        "products": [
            ("Hall hire (per hour)", 0, "each", D("150.00"), D("60.00"), D("3"), D("1"), "hall, venue, bhawan", "Up to 150 guests."),
            ("Dashain party package", 0, "pack", D("1800.00"), D("900.00"), D("1"), D("1"), "dashain, party", "Hall, decoration and sound for 5 hours."),
            ("Tihar lights and decoration", 1, "pack", D("650.00"), D("250.00"), D("1"), D("1"), "tihar, deepawali, batti", ""),
            ("Wedding mandap", 1, "pack", D("1200.00"), D("500.00"), D("1"), D("1"), "bibaha, mandap", ""),
            ("DJ and sound (per hour)", 2, "each", D("120.00"), D("50.00"), D("2"), D("1"), "dj, music, geet", ""),
            ("Photography package", 2, "pack", D("900.00"), D("350.00"), D("1"), D("1"), "photo, video", "4 hours, 200 edited photos."),
        ],
        "stock": {2: (D("40"), D("3")), 3: (D("20"), D("2"))},  # decoration kits and mandap sets
        "stock_low": 2,
    },
    {
        "slug": "test_education", "name": "Sagarmatha Education Consultancy", "industry": "education_consultancy", "type": "Education consultancy",
        "categories": ["Visa help", "Classes", "Advice"],
        "products": [
            ("Student visa application help", 0, "each", D("450.00"), D("120.00"), D("1"), D("1"), "visa, student visa", "We check your documents; Immigration NZ decides."),
            ("Document check", 0, "each", D("80.00"), D("20.00"), D("1"), D("1"), "document, check", ""),
            ("IELTS class (10 weeks)", 1, "each", D("600.00"), D("250.00"), D("1"), D("1"), "ielts, english class", ""),
            ("PTE practice test", 1, "each", D("45.00"), D("10.00"), D("1"), D("1"), "pte", ""),
            ("Course counselling (1 hour)", 2, "each", D("60.00"), D("15.00"), D("1"), D("1"), "counselling, salah", ""),
            ("Accommodation help", 2, "each", D("120.00"), D("30.00"), D("1"), D("1"), "flat, room, basne thau", ""),
        ],
    },
    {
        "slug": "test_jobs", "name": "Kaam Khoj Nepal Jobs", "industry": "jobs", "type": "Jobs",
        "categories": ["Job adverts", "Job seeker help"],
        "products": [
            ("Job advert (30 days)", 0, "each", D("99.00"), D("10.00"), D("1"), D("1"), "job ad, jagir", ""),
            ("Featured job advert", 0, "each", D("149.00"), D("15.00"), D("1"), D("1"), "featured, jagir", "Shown at the top for 30 days."),
            ("CV review", 1, "each", D("49.00"), D("10.00"), D("1"), D("1"), "cv, resume", ""),
            ("Interview practice (1 hour)", 1, "each", D("79.00"), D("20.00"), D("1"), D("1"), "interview", ""),
        ],
    },
]

CONVERSATIONS = [
    [("in", "Namaste! Do you have khasi ko masu today?"), ("out", "Namaste dai! Yes, fresh goat came this morning. How much do you need?"),
     ("in", "2 kg curry cut, pickup at 5 pm please.")],
    [("in", "Hello, can you deliver to Auckland City on Saturday?"), ("out", "Yes, we deliver to 1010 between 4 and 7 pm. Fee $6, free from $120.")],
    [("in", "Dhanyabad for the order yesterday, it was very tasty!"), ("out", "Thank you didi! See you next week.")],
]

TICKETS = [
    ("The receipt printer prints blank pages", "Since this morning the counter printer prints empty receipts.", "problem", "high", "in_progress"),
    ("How do I add a new delivery area?", "We want to start delivering to Mount Roskill.", "question", "normal", "resolved"),
    ("Please add Nepali language to receipts", "Many customers ask for Nepali text on the receipt.", "request", "low", "new"),
]
TICKET_ANSWER = "Thank you, we are looking at it. We will update you today."
