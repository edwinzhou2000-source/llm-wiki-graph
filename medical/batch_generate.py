#!/usr/bin/env python3
"""批量生成 fushun 医药产品页 v2 — 小批次 + 结构化数据"""
import os, sys, json, time, re

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import cfg, TECH_CONCEPT_DIR, SERIES_CONCEPT_DIR, PRODUCT_DIRS

# Read API key
env_file = os.path.expanduser("~/.hermes/.env")
api_key = None
with open(env_file) as f:
    for line in f:
        if line.startswith("DEEPSEEK_API_KEY="):
            api_key = line.strip().split("=", 1)[1].strip().strip('"').strip("'")
            break
if not api_key:
    print("No API key"); sys.exit(1)

import urllib.request
BASE = cfg.paths.kb_root

tech_names = [f.replace('.md', '') for f in os.listdir(os.path.join(BASE, TECH_CONCEPT_DIR)) if f.endswith('.md') and f != 'index.md']
series_names = [f.replace('.md', '') for f in os.listdir(os.path.join(BASE, SERIES_CONCEPT_DIR)) if f.endswith('.md') and f != 'index.md']

def call_deepseek(prompt):
    data = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "system", "content": "输出严格合法的JSON数组。每个对象必须完整闭合。不要markdown代码块。"}, {"role": "user", "content": prompt}],
        "temperature": 0.7, "max_tokens": 4096
    }).encode()
    req = urllib.request.Request("https://api.deepseek.com/v1/chat/completions", data=data,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    resp = urllib.request.urlopen(req, timeout=120)
    return json.loads(resp.read())["choices"][0]["message"]["content"]

def build_body(p):
    """Build markdown body from structured product data"""
    lines = [f"# {p['name']}\n"]
    lines.append("## 适应症\n" + p.get('indication_detail', p.get('summary', '')) + "\n")
    lines.append(f"## 主要成分\n{p.get('ingredients', '详见说明书')}\n")
    lines.append(f"## 用法用量\n{p.get('usage', '遵医嘱使用')}\n")
    lines.append("## 核心卖点")
    for i, point in enumerate(p.get('highlights', [p.get('summary', '')])):
        lines.append(f"- {point}")
    lines.append(f"\n## 相关概念")
    for t in p.get('tech', []):
        lines.append(f"- [[{TECH_CONCEPT_DIR}/{t}]]")
    for s in p.get('series', []):
        lines.append(f"- [[{SERIES_CONCEPT_DIR}/{s}]]")
    return '\n'.join(lines) + '\n'

BATCHES = [
    ("处方药", "心血管", 17, "降压药、降脂药、抗心绞痛、抗心律失常、抗心衰"),
    ("处方药", "抗感染", 14, "头孢类、喹诺酮类、大环内酯类、青霉素类"),
    ("处方药", "肿瘤", 12, "靶向药、化疗支持、免疫调节"),
    ("处方药", "中枢神经", 12, "抗抑郁、抗焦虑、镇静安眠、抗帕金森"),
    ("处方药", "消化代谢", 12, "降糖、消化溃疡、痛风、肝病"),
    ("OTC药品", "感冒止咳", 15, "感冒复方、止咳化痰、退热镇痛、鼻用制剂"),
    ("OTC药品", "消化肠胃", 12, "胃药、止泻、通便、消化酶、益生菌"),
    ("OTC药品", "皮肤外用药", 10, "皮炎湿疹、创口护理、消毒抗菌"),
    ("OTC药品", "维生素保健品", 15, "维生素、矿物质、蛋白粉、鱼油、辅酶Q10"),
    ("医疗器械", "诊断设备", 6, "电子血压计、血糖仪、血氧仪、体温计"),
    ("医疗器械", "耗材", 6, "注射器、输液器、敷料、采血管"),
]

CHUNK = 6  # products per API call
total_goal = sum(c for _, _, c, _ in BATCHES)
generated = 0
errors = 0

for cat_dir, sub_dir, target, theme in BATCHES:
    target_dir = os.path.join(BASE, cat_dir, sub_dir)
    os.makedirs(target_dir, exist_ok=True)
    existing = len([f for f in os.listdir(target_dir) if f.endswith('.md') and f != 'index.md'])
    needed = target - existing
    if needed <= 0:
        print(f"✅ {cat_dir}/{sub_dir}: 已有 {existing}, 跳过")
        continue
    
    print(f"\n📦 {cat_dir}/{sub_dir}: 需 {needed} 个 ({theme})")
    
    remaining = needed
    while remaining > 0:
        n = min(CHUNK, remaining)
        prompt = f"""生成 {n} 个虚构但专业的中文医药产品数据，类别: {cat_dir} > {sub_dir}，方向: {theme}。

技术平台(用这些): {tech_names}
产品系列(用这些): {series_names}
剂型可选: 片剂, 胶囊, 注射液, 口服液, 颗粒剂, 软膏, 贴剂, 喷雾剂, 外用, 粉剂
适应症: {sub_dir}

输出JSON数组(只输出JSON，不要markdown):
[{{"name":"福顺XX", "type":"{cat_dir}", "series":["系列"], "dosage_form":"剂型", "indication":"{sub_dir}", "tech":["技术"], "tags":["标签1","标签2"], "summary":"20字简介", "ingredients":"主要成分", "usage":"用法用量", "highlights":["卖点1-关联[[{TECH_CONCEPT_DIR}/xxx]]","卖点2-关联[[{SERIES_CONCEPT_DIR}/xxx]]"]}}]"""
        
        try:
            resp = call_deepseek(prompt)
            resp = resp.strip()
            if resp.startswith('```'): resp = re.sub(r'^```\w*\n|\n```$', '', resp)
            products = json.loads(resp)
            
            for p in products:
                name = p.get('name', '')
                if not name: continue
                slug = re.sub(r'[^a-z0-9\u4e00-\u9fff\-]', '', name.lower().replace(' ','-'))[:50]
                fname = f"fushun-{slug}.md"
                fpath = os.path.join(target_dir, fname)
                
                # Frontmatter
                fm = f'---\ntitle: "{name}"\ntype: "{p.get("type", cat_dir)}"\nseries: {json.dumps(p.get("series", []), ensure_ascii=False)}\ndosage_form: "{p.get("dosage_form", "")}"\nindication: "{p.get("indication", sub_dir)}"\ntech: {json.dumps(p.get("tech", []), ensure_ascii=False)}\ntags:\n'
                for t in p.get('tags', []): fm += f'  - {t}\n'
                fm += '---\n\n'
                
                with open(fpath, 'w') as f: f.write(fm + build_body(p))
                generated += 1
            
            remaining -= n
            print(f"  ✓ +{len(products)} ({generated}/{total_goal})")
            
        except json.JSONDecodeError:
            print(f"  ⚠ JSON解析失败，重试... (剩余{remaining})")
            time.sleep(3)
        except Exception as e:
            print(f"  ❌ {e}")
            errors += 1
            remaining -= n  # 跳过这批次
        
        time.sleep(1.5)

print(f"\n{'='*50}\n完成: {generated} 个, {errors} 错误\n{'='*50}")
