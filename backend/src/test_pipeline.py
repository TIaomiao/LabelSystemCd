#!/usr/bin/env python
"""测试改进后的诊断流程"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from pipelines.diagnosis_pipeline import DiagnosisPipeline

def test_patient(patient_id: str):
    """测试指定患者"""
    print(f"\n{'='*60}")
    print(f"测试患者: {patient_id}")
    print(f"{'='*60}\n")
    
    try:
        pipeline = DiagnosisPipeline()
        result = pipeline.run(patient_id)
        
        print(f"\n处理完成！")
        print(f"输出目录: {result['output_dir']}")
        
        # 显示关键指标
        metrics = result['metrics']['requested_metrics']
        print(f"\n关键指标:")
        for m in metrics:
            if m['status'] == 'ok':
                print(f"  {m['name']}: {m['value']:.2f} {m['unit']}")
            else:
                print(f"  {m['name']}: {m['status']}")
        
        return True
    except Exception as e:
        print(f"\n❌ 处理失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 测试一个患者
    patient_id = sys.argv[1] if len(sys.argv) > 1 else "0004335617"
    success = test_patient(patient_id)
    sys.exit(0 if success else 1)

