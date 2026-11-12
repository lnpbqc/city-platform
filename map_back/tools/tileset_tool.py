# 用以方便转换tileset.json 的经纬度和椭球高
# python tileset_tool.py tileset.json
# python tileset_tool.py tileset.json --lon 116.3912 --lat 39.9073 --height 44.5

import json
import math
import argparse
import sys
from pyproj import Transformer

# 初始化坐标转换器 (WGS84 <-> ECEF)
# always_xy=True 确保输入输出格式为 (经度, 纬度) 而不是 (纬度, 经度)
transformer_to_ecef = Transformer.from_crs("epsg:4326", "epsg:4978", always_xy=True)
transformer_to_wgs84 = Transformer.from_crs("epsg:4978", "epsg:4326", always_xy=True)

def get_info_from_transform(transform):
    """从 transform 矩阵反解经纬度和椭球高"""
    ecef_x = transform[12]
    ecef_y = transform[13]
    ecef_z = transform[14]
    lon, lat, height = transformer_to_wgs84.transform(ecef_x, ecef_y, ecef_z)
    return lon, lat, height

def create_transform(lon, lat, height):
    """根据经纬度、椭球高生成标准的列主序 4x4 矩阵"""
    ecef_x, ecef_y, ecef_z = transformer_to_ecef.transform(lon, lat, height)
    
    lon_rad = math.radians(lon)
    lat_rad = math.radians(lat)
    
    # 局部坐标系：X=East, Y=North, Z=Up
    east_x, east_y, east_z = -math.sin(lon_rad), math.cos(lon_rad), 0.0
    north_x = -math.sin(lat_rad) * math.cos(lon_rad)
    north_y = -math.sin(lat_rad) * math.sin(lon_rad)
    north_z = math.cos(lat_rad)
    up_x = math.cos(lat_rad) * math.cos(lon_rad)
    up_y = math.cos(lat_rad) * math.sin(lon_rad)
    up_z = math.sin(lat_rad)
    
    # 列主序 (Column-major) 矩阵
    transform = [
        east_x, north_x, up_x, 0.0,
        east_y, north_y, up_y, 0.0,
        east_z, north_z, up_z, 0.0,
        ecef_x, ecef_y, ecef_z, 1.0
    ]
    return [round(val, 10) for val in transform]

def main():
    parser = argparse.ArgumentParser(description="读取或修改 3D Tiles 的经纬度与椭球高")
    parser.add_argument("file", help="tileset.json 的文件路径")
    parser.add_argument("--lon", type=float, help="新的经度 (保留原值则不填)")
    parser.add_argument("--lat", type=float, help="新的纬度 (保留原值则不填)")
    parser.add_argument("--height", type=float, help="新的椭球高/海拔 (保留原值则不填)")
    args = parser.parse_args()

    # 1. 读取 JSON 文件
    try:
        with open(args.file, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        print(f"读取文件失败: {e}")
        sys.exit(1)

    # 2. 检查 transform 是否存在
    if 'root' not in data or 'transform' not in data['root']:
        print("错误：该 JSON 文件中找不到 root.transform")
        sys.exit(1)

    current_transform = data['root']['transform']
    
    # 3. 显示当前信息
    cur_lon, cur_lat, cur_height = get_info_from_transform(current_transform)
    print("--- 当前状态 ---")
    print(f"经度: {cur_lon:.6f}")
    print(f"纬度: {cur_lat:.6f}")
    print(f"椭球高: {cur_height:.3f} 米")

    # 4. 判断是否进行了修改操作
    if args.lon is not None or args.lat is not None or args.height is not None:
        new_lon = args.lon if args.lon is not None else cur_lon
        new_lat = args.lat if args.lat is not None else cur_lat
        new_height = args.height if args.height is not None else cur_height
        
        print("\n--- 修改为 ---")
        print(f"经度: {new_lon:.6f}")
        print(f"纬度: {new_lat:.6f}")
        print(f"椭球高: {new_height:.3f} 米")

        # 生成新矩阵并覆盖
        data['root']['transform'] = create_transform(new_lon, new_lat, new_height)
        
        try:
            with open(args.file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            print(f"\n✅ 修改成功！已保存至 {args.file}")
        except Exception as e:
            print(f"写入文件失败: {e}")

if __name__ == "__main__":
    main()