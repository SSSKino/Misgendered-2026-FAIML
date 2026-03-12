import json

with open(r'C:\Users\NINGMEI\Downloads\faiml_multithreaded - 副本\data\inputs\rawdata\CV.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

# 过滤：只保留名字（第一个单词）不在 ['Liam','Taylor','Jordan'] 中的记录
filtered = [item for item in data if item['name'].split()[0] not in ['Liam', 'Taylor', 'Jordan']]

with open(r'C:\Users\NINGMEI\Downloads\faiml_multithreaded - 副本\data\inputs\rawdata\CV_filtered.json', 'w', encoding='utf-8') as f:
    json.dump(filtered, f, indent=2, ensure_ascii=False)

print(f"原始记录数：{len(data)}，删除后记录数：{len(filtered)}")