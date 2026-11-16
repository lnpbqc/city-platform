import pytest

from tools.tileset_tool import create_transform, get_info_from_transform, relocate_transform


def test_transform_uses_enu_columns_and_preserves_pose_in_height_only_edit():
    enu = create_transform(0, 0, 123)
    assert enu[:12] == [0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0]
    # Model axes include a heading change and a non-unit scale.
    model = [0, 0, 2, 0, 0, -3, 0, 0, 4, 0, 0, 0, *enu[12:]]
    raised = relocate_transform(model, 0, 0, 456)
    assert raised[:12] == model[:12]
    assert get_info_from_transform(raised) == pytest.approx((0, 0, 456))
    moved = relocate_transform(raised, 90, 0, 500)
    assert moved[:12] == pytest.approx([0, 0, 2, 0, 3, 0, 0, 0, 0, 4, 0, 0])
    assert get_info_from_transform(moved) == pytest.approx((90, 0, 500))
