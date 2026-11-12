from app.services.poi_style import poi_style


def test_semantics_and_scale_eligibility():
    assert poi_style({'name': '广州南站', 'railway': 'station'}, 100)['eligible']
    assert poi_style({'name': '大学医院', 'amenity': 'hospital'}, 10)['eligible']
    assert not poi_style({'name': '咖啡时光', 'amenity': 'cafe'}, 10)['eligible']
    assert poi_style({'name': '咖啡时光', 'amenity': 'cafe'}, 3)['eligible']
    assert poi_style({'name': '广州大学', 'amenity': 'university'}, 10)['category'] == '教育'
    assert poi_style({'name': '广州酒店', 'tourism': 'hotel'}, 3)['category'] == '住宿'
    assert poi_style({'name': '大学城消防站', 'amenity': 'fire_station'}, 10)['category'] == '公共服务'
    assert poi_style({'name': '纪念碑', 'historic': 'memorial'}, 10)['category'] == '文旅'
    assert poi_style({'name': '省博物馆', 'category': '文旅', 'tourism': 'museum'}, 100)['eligible']


def test_unnamed_and_generic_never_become_background_labels():
    for name in ['', '未命名 POI', 'restaurant', '餐馆', '12345']:
        assert not poi_style({'name': name, 'amenity': 'restaurant'}, .5)['eligible']
    assert poi_style({'name': 'English', 'name:zh': '中文专名'}, 1)['name'] == '中文专名'
