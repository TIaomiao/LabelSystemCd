from flask import Blueprint, jsonify, current_app, request
import csv
import os
import re
import pandas as pd
import time
import threading
from flask_login import login_required, current_user
from models import CviCaseCatalog

hospital_browser_bp = Blueprint('hospital_browser', __name__)

# Allowed users
ALLOWED_USERS = ['lzq', 'pengliang', 'wanglujing']
# ALLOWED_USERS = ['pengliang', 'wanglujing']

def check_permission():
    if not current_user.is_authenticated:
        return False
    return bool(getattr(current_user, 'is_admin', False)) or current_user.username in ALLOWED_USERS

@hospital_browser_bp.before_request
def before_request():
    if request.method != 'OPTIONS':  # Allow CORS preflight
        if not current_user.is_authenticated:
            return jsonify({'error': 'Unauthorized'}), 401
        if not check_permission():
            return jsonify({'error': 'Forbidden'}), 403

# 配置：医院 ID -> 原始病例目录、病种 Excel 目录、结果 output 目录、ID列名
HOSPITAL_CONFIG = {
    'all': {
        'dataset': 'CMR_ALL',
        'name': '昆医附二院',
        'raw_root': '/home/Larry/data/CMR_ALL',
        'excel_root': '/home/Larry/code/Ziqiu/MRIAgent/hospital-data/昆医附二院2014-2026.1.29病例分类',
        'output_dir': '/home/Larry/code/Ziqiu/MRIAgent/src/output/new_CMR_ALL',
        'id_cols': ['登记号']
    },
    'chendu': {
        'dataset': 'CMR_Chendu',
        'name': '成都中心',
        'raw_root': '/home/Larry/data/CMR_Chendu',
        'output_dir': '/home/Larry/code/Ziqiu/MRIAgent/src/output/new_CMR_Chendu',
        'id_cols': ['登记号', '住院号', '影像号', '检查号', 'studyid', '病人id']
    },
    'scs': {
        'dataset': 'CMR_SCS',
        'name': '四川省人民医院',
        'raw_root': '/home/Larry/data/CMR_SCS',
        'excel_root': '/home/Larry/code/Ziqiu/MRIAgent/hospital-data/四川省人民医院',
        'output_dir': '/home/Larry/code/Ziqiu/MRIAgent/src/output/new_CMR_SCS',
        'id_cols': ['studyid', 'beststudyid', '检查号', '病人id']
    },
    'ya': {
        'dataset': 'CMR_YA',
        'name': '延安医院',
        'raw_root': '/home/Larry/data/CMR_YA/merged_files',
        'excel_root': '/home/Larry/code/Ziqiu/MRIAgent/hospital-data/延安医院',
        'output_dir': '/home/Larry/code/Ziqiu/MRIAgent/src/output/new_CMR_YA',
        'id_cols': ['住院号', '影像号']
    }
}

# Cache for the hospital tree
# Structure: { 'data': [...], 'timestamp': 1234567890 }
TREE_CACHE = {
    'data': None,
    'timestamp': 0
}
CACHE_DURATION = 3600  # 1 hour
CACHE_LOCK = threading.Lock()

def normalize_case_id(raw_val):
    if raw_val is None or pd.isna(raw_val):
        return []

    val_str = str(raw_val).strip()
    if not val_str:
        return []
    if val_str.endswith('.0'):
        val_str = val_str[:-2]

    candidates = [val_str]
    if val_str.isdigit():
        candidates.append(str(int(val_str)))

    mr_match = re.search(r'(MR\d+)', val_str)
    if mr_match:
        candidates.append(mr_match.group(1))

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(candidates))

def get_output_cases_map(output_dir):
    """
    扫描 output 目录，构建 { 'normalized_id': 'case_folder_name' } 映射
    normalized_id 是去除前导零的字符串
    """
    if not os.path.exists(output_dir):
        return {}
    
    mapping = {}
    try:
        for folder_name in os.listdir(output_dir):
            if not os.path.isdir(os.path.join(output_dir, folder_name)):
                continue

            mapping[folder_name] = folder_name
            
            # Folder names may contain a study key, date, and optional label.
            # 提取第一部分作为 ID
            if '_' in folder_name:
                parts = folder_name.split('_')
                if parts:
                    raw_id_str = parts[0]
                    # 尝试转为 int 再转回 str 以去除前导零 (如果全是数字)
                    if raw_id_str.isdigit():
                        norm_id = str(int(raw_id_str))
                        mapping[norm_id] = folder_name
                    else:
                        # 如果不是纯数字，保留原样
                        mapping[raw_id_str] = folder_name
            else:
                # 尝试匹配 SCS 格式 (如 ADMR1202402250155)
                # 提取 MR... 部分作为 ID
                match = re.search(r'(MR\d+)', folder_name)
                if match:
                    mr_id = match.group(1)
                    mapping[mr_id] = folder_name
                elif folder_name.isdigit():
                    # 处理纯数字文件夹 (如延安医院)
                    norm_id = str(int(folder_name))
                    mapping[norm_id] = folder_name
                else:
                    mapping[folder_name] = folder_name
    except Exception as e:
        print(f"Error scanning output dir {output_dir}: {e}")
    
    return mapping

def match_case(raw_val, output_map, output_case_names):
    for candidate in normalize_case_id(raw_val):
        if candidate in output_map:
            return output_map[candidate]
        if len(candidate) >= 4:
            for folder_name in output_case_names:
                if candidate in folder_name:
                    return folder_name
    return None

def scan_hospital_excel_files(hospital_key):
    """
    扫描医院 Excel 文件，返回病种下的源清单数量和当前 output 可浏览病例。
    """
    config = HOSPITAL_CONFIG.get(hospital_key)
    if not config:
        return {}
    
    raw_root = config['raw_root']
    excel_root = config.get('excel_root') or raw_root
    output_dir = config['output_dir']
    id_cols = config['id_cols']
    
    if not os.path.exists(excel_root):
        print(f"Excel root not found: {excel_root}")
        return {}

    # 获取 output 目录的 ID 映射
    output_map = get_output_cases_map(output_dir)
    output_case_names = sorted(set(output_map.values()))
    
    tree = {}
    
    try:
        excel_files = [
            filename for filename in os.listdir(excel_root)
            if filename.endswith('.xlsx') and not filename.startswith('~')
        ]

        # 如果目录本身就是病例目录，而不是疾病 Excel 仓库，则直接按目录建一个“全部病例”分组
        if not excel_files:
            matched_cases = []
            for folder_name in os.listdir(raw_root):
                folder_path = os.path.join(raw_root, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                raw_id_str = folder_name.strip()
                if raw_id_str.endswith('.0'):
                    raw_id_str = raw_id_str[:-2]
                norm_val = str(int(raw_id_str)) if raw_id_str.isdigit() else raw_id_str
                if norm_val in output_map:
                    matched_cases.append(output_map[norm_val])
                elif raw_id_str in output_map:
                    matched_cases.append(output_map[raw_id_str])
            if matched_cases:
                tree['全部病例'] = {
                    'patients': sorted(list(set(matched_cases))),
                    'source_count': len([
                        name for name in os.listdir(raw_root)
                        if os.path.isdir(os.path.join(raw_root, name))
                    ]),
                }
            return tree

        # 遍历 .xlsx 文件
        for filename in excel_files:
                
            file_path = os.path.join(excel_root, filename)
            disease_name = os.path.splitext(filename)[0]
            
            # 读取 Excel
            try:
                df = pd.read_excel(file_path)
            except Exception as e:
                print(f"Error reading {filename}: {e}")
                continue
            
            # 查找所有可用 ID 列；不同医院/不同病种表可能列名不一致
            search_cols = [col for col in id_cols if col in df.columns]

            if not search_cols:
                print(f"ID column {id_cols} not found in {filename}")
                tree[disease_name] = {'patients': [], 'source_count': len(df)}
                continue
            
            # 提取 ID 并匹配
            matched_cases = []
            for _, row in df[search_cols].iterrows():
                for col in search_cols:
                    matched_case = match_case(row[col], output_map, output_case_names)
                    if matched_case:
                        matched_cases.append(matched_case)
                        break

            # 即使当前 output 中没有匹配病例，也保留病种节点，避免医院下退化成扁平列表。
            tree[disease_name] = {
                'patients': sorted(list(set(matched_cases))),
                'source_count': len(df),
            }
                
    except Exception as e:
        print(f"Error scanning {raw_root}: {e}")
        return {}

    return tree

def generate_tree_data():
    """
    Generate the full tree data
    """
    result = []
    for key, config in HOSPITAL_CONFIG.items():
        try:
            disease_map = scan_hospital_excel_files(key)
            diseases = []
            for d_name, disease_info in disease_map.items():
                p_list = disease_info.get('patients', []) if isinstance(disease_info, dict) else disease_info
                source_count = disease_info.get('source_count', len(p_list)) if isinstance(disease_info, dict) else len(p_list)
                diseases.append({
                    'name': d_name,
                    'patients': p_list,
                    'dataset': os.path.basename(config['output_dir']),
                    'source_count': source_count,
                    'available_count': len(p_list),
                })
            
            diseases.sort(key=lambda x: x['name'])
            
            result.append({
                'id': key,
                'name': config['name'],
                'dataset': config.get('dataset', ''),
                'diseases': diseases,
                'source_count': sum(item['source_count'] for item in diseases),
                'available_count': len({patient for item in diseases for patient in item['patients']}),
            })
        except Exception as e:
            print(f"Error processing hospital {key}: {e}")
            result.append({
                'id': key,
                'name': config['name'] + " (Error)",
                'diseases': []
            })
    return result


def _manifest_case_count(path_text):
    if not path_text:
        return None
    manifest_path = os.path.expanduser(str(path_text))
    if not os.path.isfile(manifest_path):
        return None
    count = 0
    try:
        with open(manifest_path, 'r', encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                if str(row.get('source_relative_dir') or '').strip() and str(row.get('case_sequence') or '').strip():
                    count += 1
    except OSError:
        return None
    return count


def _count_dirs_at_depth(root_path, depth):
    if depth < 1 or not os.path.isdir(root_path):
        return 0
    current = [root_path]
    for _ in range(depth):
        next_level = []
        for parent in current:
            try:
                next_level.extend(
                    os.path.join(parent, name)
                    for name in os.listdir(parent)
                    if not name.startswith('.') and os.path.isdir(os.path.join(parent, name))
                )
            except OSError:
                continue
        current = next_level
    return len(current)


def _raw_candidate_count(library):
    manifest_count = _manifest_case_count(library.get('case_id_manifest'))
    if manifest_count is not None:
        return manifest_count, '私有接入清单'
    root_path = os.path.expanduser(str(library.get('path') or ''))
    try:
        depth = max(1, int(library.get('case_dir_depth') or 1))
    except (TypeError, ValueError):
        depth = 1
    return _count_dirs_at_depth(root_path, depth), f'目录第 {depth} 层'


def _classification_info(dataset):
    config = next(
        (item for item in HOSPITAL_CONFIG.values() if item.get('dataset') == dataset),
        None,
    )
    if config is None:
        return {
            'status': 'pending',
            'label': '待配置病种分类',
            'category_count': 0,
            'output_count': 0,
        }
    excel_root = config.get('excel_root') or config.get('raw_root')
    category_count = 0
    if excel_root and os.path.isdir(excel_root):
        try:
            category_count = len([
                name for name in os.listdir(excel_root)
                if name.lower().endswith('.xlsx') and not name.startswith('~')
            ])
        except OSError:
            category_count = 0
    output_map = get_output_cases_map(config.get('output_dir') or '')
    output_count = len(set(output_map.values()))
    if category_count:
        status = 'classified'
        label = f'已配置 {category_count} 个病种清单'
    elif output_count:
        status = 'flat'
        label = '已接入，当前按全部病例浏览'
    else:
        status = 'pending'
        label = '待配置病种分类'
    return {
        'status': status,
        'label': label,
        'category_count': category_count,
        'output_count': output_count,
    }


def generate_inventory_data():
    items = []
    for library in current_app.config.get('CVI_LIBRARY_MULTICENTER_ROOTS', []) or []:
        dataset = str(library.get('dataset') or '').strip()
        if not dataset:
            continue
        raw_count, raw_count_basis = _raw_candidate_count(library)
        catalog_query = CviCaseCatalog.query.filter_by(source='functional', dataset=dataset)
        catalog_count = catalog_query.count()
        dicom_count = catalog_query.filter_by(has_dicom=True).count()
        imported_count = catalog_query.filter(CviCaseCatalog.cvi_study_id.isnot(None)).count()
        classification = _classification_info(dataset)
        if catalog_count == 0:
            access_status = 'not_registered'
            access_label = '尚未登记到工作站目录'
        elif classification['status'] == 'pending':
            access_status = 'registered_pending_classification'
            access_label = '已登记，待分类'
        elif classification['output_count'] == 0:
            access_status = 'registered_no_output'
            access_label = '已登记，暂无分类输出'
        else:
            access_status = 'browsable'
            access_label = '已接入医院分类浏览'
        items.append({
            'dataset': dataset,
            'label': str(library.get('label') or dataset),
            'raw_candidate_count': raw_count,
            'raw_count_basis': raw_count_basis,
            'catalog_count': catalog_count,
            'dicom_case_count': dicom_count,
            'imported_count': imported_count,
            'classified_output_count': classification['output_count'],
            'classification_status': classification['status'],
            'classification_label': classification['label'],
            'classification_category_count': classification['category_count'],
            'access_status': access_status,
            'access_label': access_label,
        })
    return {
        'items': items,
        'totals': {
            'datasets': len(items),
            'raw_candidates': sum(item['raw_candidate_count'] for item in items),
            'catalog': sum(item['catalog_count'] for item in items),
            'imported': sum(item['imported_count'] for item in items),
            'classified_output': sum(item['classified_output_count'] for item in items),
        },
        'count_definitions': {
            'raw_candidate_count': '原始目录或私有接入清单中的候选 Study 数',
            'catalog_count': '已登记到 CMR 工作站病例目录的记录数',
            'imported_count': '已实际导入 CVI 影像服务的病例数',
            'classified_output_count': 'MRIAgent new_CMR_* 分类 output 的唯一病例文件夹数；不等于病种清单匹配数',
        },
    }


@hospital_browser_bp.route('/inventory', methods=['GET'])
def get_hospital_inventory():
    return jsonify(generate_inventory_data())

@hospital_browser_bp.route('/tree', methods=['GET'])
def get_hospital_tree():
    """
    返回完整的医院数据树结构
    支持缓存和强制刷新
    """
    force_refresh = request.args.get('refresh') == 'true'
    current_time = time.time()
    
    with CACHE_LOCK:
        # Check cache validity
        if not force_refresh and TREE_CACHE['data'] is not None and (current_time - TREE_CACHE['timestamp'] < CACHE_DURATION):
            return jsonify(TREE_CACHE['data'])
        
        # Regenerate data
        print("Regenerating hospital tree data...")
        new_data = generate_tree_data()
        
        # Update cache
        TREE_CACHE['data'] = new_data
        TREE_CACHE['timestamp'] = current_time
        
        return jsonify(new_data)

@hospital_browser_bp.route('/match/<hospital_id>/<path:patient_raw_id>', methods=['GET'])
def match_patient(hospital_id, patient_raw_id):
    config = HOSPITAL_CONFIG.get(hospital_id)
    if not config:
        return jsonify({'error': 'Invalid hospital ID'}), 400
        
    output_map = get_output_cases_map(config['output_dir'])
    
    # 尝试匹配
    norm_id = patient_raw_id
    if norm_id.isdigit():
        norm_id = str(int(norm_id))
        
    if norm_id in output_map:
        return jsonify({
            'found': True,
            'dataset': config['output_dir'],
            'case_id': output_map[norm_id]
        })
    else:
        return jsonify({
            'found': False,
            'dataset': config['output_dir']
        })
