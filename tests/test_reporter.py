import pytest
from pathlib import Path
from src.core.reporter import generate_report

def test_generate_report(tmp_path):
    results = [
        {
            'name': 'test_mission_1',
            'success': True,
            'status': 'safe',
            'messages': ['All systems go.'],
            'metrics': {'gsd': 2.5, 'blur': 0.5},
            'altitude': 100,
            'speed': 5
        },
        {
            'name': 'test_mission_2',
            'success': True,
            'status': 'warning',
            'messages': ['Altitude is high.'],
            'metrics': {'gsd': 5.0, 'blur': 1.0},
            'altitude': 150,
            'speed': 8
        },
        {
            'name': 'failed_file.gpkg',
            'success': False,
            'status': 'danger',
            'messages': ['File corrupted.'],
            'metrics': {},
            'altitude': 100,
            'speed': 5
        }
    ]
    
    report_path = generate_report(results, tmp_path)
    assert report_path.exists()
    assert report_path.suffix == '.html'
    
    content = report_path.read_text(encoding='utf-8')
    assert 'test_mission_1' in content
    assert 'test_mission_2' in content
    assert 'failed_file.gpkg' in content
    assert 'SAFE' in content
    assert 'WARNING' in content
    assert 'DANGER' in content
