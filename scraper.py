from craigslist import CraigslistHousing
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, DateTime, Float, Boolean
from sqlalchemy.orm import sessionmaker
from dateutil.parser import parse
import math
from slackclient import SlackClient
import settings

engine = create_engine('sqlite:///listings.db', echo=False)

Base = declarative_base()

class Listing(Base):
    __tablename__ = 'listings'

    id = Column(Integer, primary_key=True)
    link = Column(String, unique=True)
    created = Column(DateTime)
    geotag = Column(String)
    lat = Column(Float)
    lon = Column(Float)
    name = Column(String)
    price = Column(Float)
    location = Column(String)
    cl_id = Column(Integer, unique=True)
    area = Column(String)
    bart_stop = Column(String)

Base.metadata.create_all(engine)

Session = sessionmaker(bind=engine)
session = Session()

areas = ["eby", "nby", "sfc", "sby"]

bart_stations = {
    "oakland_19th": [37.8118051,-122.2720873],
    "macarthur": [37.8265657,-122.2686705],
    "rockridge": [37.841286,-122.2566329],
    "downtown_berkeley": [37.8629541,-122.276594],
    "north_berkeley": [37.8713411,-122.2849758]
}

neighborhoods = ["berkeley north", "berkeley", "rockridge", "adams point", "oakland lake merritt", "cow hollow", "piedmont", "pac hts", "pacific heights"]

boxes = {
    "adams_point": [
        [37.81589,	-122.26081],
        [37.80789, -122.25000]
    ],
    "piedmont": [
        [37.83237, -122.25386],
        [37.82240, -122.24768]
    ],
    "rockridge": [
        [37.84680, -122.25944],
        [37.83826, -122.24073]
    ],
    "berkeley": [
        [37.86781, -122.26502],
        [37.86226, -122.25043]
    ],
    "north_berkeley": [
        [37.87655, -122.28974],
        [37.86425, -122.26330]
    ],
    "pac_heights": [
        [37.79850, -122.44784],
        [37.79124, -122.42381]
    ],
    "lower_pac_heights": [
        [37.78873, -122.44544],
        [37.78554, -122.42878]
    ]
}

def coord_distance(lat1, lon1, lat2, lon2):
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    c = 2 * math.asin(math.sqrt(a))
    km = 6367 * c
    return km

def in_box(coords, box):
    if box[1][0] < coords[0] < box[0][0] and box[0][1] < coords[1] < box[1][1]:
        return True
    return False

def scrape_area(area):
    cl_h = CraigslistHousing(site='sfbay', area=area, category='apa',
                             filters={'max_price': 2800, "min_price": 1800})

    results = []
    for result in cl_h.get_results(sort_by='newest', geotagged=True, limit=100):
        listing = session.query(Listing).filter_by(cl_id=result["id"]).first()
        if listing is None:
            area = ""
            if result["where"] is None:
                continue

            result["near_bart"] = False
            result["area_found"] = False
            result["bart_dist"] = "N/A"
            bart = ""
            min_dist = None
            lat = 0
            lon = 0
            if result["geotag"] is not None:
                for a, coords in boxes.items():
                    if in_box(result["geotag"], coords):
                        area = a
                        result["area_found"] = True

                for station, coords in bart_stations.items():
                    dist = coord_distance(coords[0], coords[1], result["geotag"][0], result["geotag"][1])
                    if (min_dist is None or dist < min_dist) and dist < settings.MAX_BART_DIST:
                        bart = station
                        result["near_bart"] = True

                    if (min_dist is None or dist < min_dist):
                        result["bart_dist"] = dist

                lat = result["geotag"][0]
                lon = result["geotag"][1]

            if len(area) == 0:
                for hood in neighborhoods:
                    if hood in result["where"].lower():
                        area = hood

            price = 0
            try:
                price = float(result["price"].replace("$", ""))
            except Exception:
                pass
            listing = Listing(
                link=result["url"],
                created=parse(result["datetime"]),
                lat=lat,
                lon=lon,
                name=result["name"],
                price=price,
                location=result["where"],
                cl_id=result["id"],
                area=area,
                bart_stop=bart
            )
            session.add(listing)
            session.commit()
            result["area"] = area
            result["bart_stop"] = bart
            if len(bart) > 0 or len(area) > 0:
                results.append(result)

    return results


def post_listing_to_slack(sc, listing):
    desc = "{0} | {1} | {2} | {3} | <{4}>".format(listing["area"], listing["price"], listing["bart_dist"], listing["name"], listing["url"])
    sc.api_call(
        "chat.postMessage", channel="#housing", text=desc,
        username='pybot', icon_emoji=':robot_face:'
    )

sc = SlackClient(settings.SLACK_TOKEN)

def do_scrape():
    all_results = []
    for area in areas:
        all_results += scrape_area(area)

    for result in all_results:
        post_listing_to_slack(sc, result)
