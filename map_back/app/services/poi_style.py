"""Background POI eligibility; raw objects remain available to nearby/detail APIs."""
import re


def poi_style(properties, meters_per_pixel):
    def text(*keys):
        return next((properties[key].strip() for key in keys if isinstance(properties.get(key), str) and properties[key].strip()), '')
    raw = text('category', '类别', '類別', 'amenity', 'shop', 'tourism', 'railway', 'aeroway', 'leisure', 'historic', 'fclass').lower()
    category, priority, maximum_scale = '其他', 10, 1
    if re.search(r'餐饮|餐飲|restaurant|cafe|food|bar|pub|fast_food', raw):
        category, priority, maximum_scale = '餐饮', 40, 5
    elif re.search(r'住宿|hotel|hostel|motel|guest_house', raw):
        category, priority, maximum_scale = '住宿', 50, 5
    elif re.search(r'医疗|醫療|hospital|clinic|pharmacy|doctors|dentist', raw):
        category, priority, maximum_scale = '医疗', 85, 20
    elif re.search(r'教育|school|university|college|kindergarten|library', raw):
        category, priority, maximum_scale = '教育', 80, 20
    elif re.search(r'fire_station|police', raw):
        category, priority, maximum_scale = '公共服务', 65, 20
    elif re.search(r'交通|parking|station|bus|fuel|aerodrome|airport|halt|stop_position', raw):
        category, priority, maximum_scale = '交通', 60, 5
        if properties.get('railway') == 'station' or properties.get('aeroway') == 'aerodrome' or raw in ('airport', 'aerodrome', '火车站', '机场'):
            priority, maximum_scale = 100, float('inf')
    elif re.search(r'购物|購物|商|mall|supermarket|convenience|shop', raw) or isinstance(properties.get('shop'), str):
        category, priority, maximum_scale = '购物', 45, 5
    elif re.search(r'文旅|景点|景點|attraction|museum|viewpoint|park|garden|artwork|historic|memorial|monument', raw):
        category, priority, maximum_scale = '文旅', 75, 20
        if re.search(r'attraction|museum|景点|景點', raw) or properties.get('tourism') in ('attraction', 'museum'):
            priority, maximum_scale = 95, float('inf')
    elif re.search(r'公共|police|fire_station|post_office|townhall|community_centre|toilets|drinking_water|waste|recycling', raw):
        category, priority, maximum_scale = '公共服务', 65, 20
        if re.search(r'toilets|drinking_water|waste|recycling', raw):
            priority, maximum_scale = 15, 1
    name = text('name:zh', '名称', '名稱', 'name')
    if re.fullmatch(r'未命名(?:\s*POI)?|其他|餐馆|餐厅|商店|学校|医院|停车场|图书馆|酒店|便利店|卫生间|restaurant|cafe|shop|school|hospital|parking|library|hotel|toilets|atm|\d+', name, re.I):
        name = ''
    return {'category': category, 'priority': priority, 'name': name,
            'eligible': bool(name) and meters_per_pixel <= maximum_scale}
