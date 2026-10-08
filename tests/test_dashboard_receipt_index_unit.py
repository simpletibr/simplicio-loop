from simplicio_loop.dashboard import runs


def test_quality_matrix_is_listed_among_the_run_receipts(tmp_path):
    run_dir = tmp_path / 'run-1'
    run_dir.mkdir()
    (run_dir / 'quality-matrix.json').write_text('{}', encoding='utf-8')
    names = [item['name'] for item in runs.run_detail(run_dir)['receipts']]
    assert 'quality-matrix.json' in names


def test_run_without_quality_matrix_does_not_list_it(tmp_path):
    run_dir = tmp_path / 'run-2'
    run_dir.mkdir()
    names = [item['name'] for item in runs.run_detail(run_dir)['receipts']]
    assert 'quality-matrix.json' not in names
