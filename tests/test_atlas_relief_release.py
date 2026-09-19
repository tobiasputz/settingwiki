from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def test_relief_assets_and_masks_are_shipped():
    atlas=ROOT/'static'/'atlas'/'kiragon'
    required={'albedo.webp','height.png','normal.png','water-mask.png','land-mask.png','cloud-mask.png','major-label-mask.png','ao.png','roughness.png','material-map.png','profile.json'}
    assert required.issubset({p.name for p in atlas.iterdir()})
    assert (ROOT/'static'/'atlas-relief.js').is_file()


def test_atlas_template_has_progressive_relief_fallback():
    text=(ROOT/'templates'/'map.html').read_text(encoding='utf-8')
    assert 'atlasReliefCanvas' in text
    assert 'data-map-relief' in text
    assert 'atlas-relief.js?v=10200' in text
    assert 'id="atlasImage"' in text  # original image remains the fallback/interaction surface


def test_relief_renderer_consumes_cloud_and_label_masks():
    text=(ROOT/'static'/'atlas-relief.js').read_text(encoding='utf-8')
    assert 'u_material' in text
    assert 'u_label' in text
    assert 'cloudShadow' in text
    assert 'terrainShadow' in text
    assert 'u_material' in text
    assert 'expandedLabel' in text
    assert 'u_label_declutter' in text


def test_relief_renderer_is_displaced_perspective_and_reprojects_interactions():
    relief=(ROOT/'static'/'atlas-relief.js').read_text(encoding='utf-8')
    mapjs=(ROOT/'static'/'map.js').read_text(encoding='utf-8')
    profile=(ROOT/'static'/'atlas'/'kiragon'/'profile.json').read_text(encoding='utf-8')
    assert 'attribute float a_height' in relief
    assert 'u_camera_distance' in relief
    assert 'u_height_scale' in relief
    assert 'projectUV(u, v)' in relief
    assert 'unprojectClient(clientX, clientY)' in relief
    assert 'cloudSuppression' in relief
    assert 'syncReliefProjection' in mapjs
    assert 'relief.unprojectClient' in mapjs
    assert 'cinematic-displaced-v3' in profile


def test_3d_mode_keeps_2d_fallback_and_warps_raster_layers_in_webgl():
    relief=(ROOT/'static'/'atlas-relief.js').read_text(encoding='utf-8')
    css=(ROOT/'static'/'wiki.css').read_text(encoding='utf-8')
    template=(ROOT/'templates'/'map.html').read_text(encoding='utf-8')
    assert 'loadOverlayTextures' in relief
    assert "querySelectorAll('.atlas-overlay-layer')" in relief
    assert '.atlas-overlay-layer{visibility:hidden}' in css
    assert 'id="atlasImage"' in template


def test_high_resolution_equivalent_maps_use_uv_terrain_assets():
    relief=(ROOT/'static'/'atlas-relief.js').read_text(encoding='utf-8')
    mapjs=(ROOT/'static'/'map.js').read_text(encoding='utf-8')
    assert 'aspectCompatible(expectedWidth, expectedHeight, fallbackWidth, fallbackHeight)' in relief
    assert 'this.mapWidth = fallbackWidth' in relief
    assert 'this.canvas.style.width = `${fallbackWidth}px`' in relief
    assert 'maxRenderDimension || 4096' in relief
    assert 'textureSource(this.image, this.maxTextureDimension)' in relief
    assert 'lastError' in relief
    assert '2.5D terrain unavailable:' in mapjs


def test_relief_texture_orientation_matches_atlas_uvs():
    relief=(ROOT/'static'/'atlas-relief.js').read_text(encoding='utf-8')
    assert 'UNPACK_FLIP_Y_WEBGL, false' in relief
    assert 'UNPACK_FLIP_Y_WEBGL, true' not in relief


def test_cinematic_relief_uses_multiscale_height_lighting_and_water_surface():
    relief=(ROOT/'static'/'atlas-relief.js').read_text(encoding='utf-8')
    profile=(ROOT/'static'/'atlas'/'kiragon'/'profile.json').read_text(encoding='utf-8')
    for token in ('terrainShadow', 'terrainNormal', 'cinematicGrade', 'u_height', 'u_material', 'cloudShadow', 'shore'):
        assert token in relief
    assert 'cinematic-displaced-v3' in profile


def test_cloud_mask_separates_atmosphere_from_snow_terrain():
    from PIL import Image
    import numpy as np
    cloud=np.asarray(Image.open(ROOT/'static'/'atlas'/'kiragon'/'cloud-mask.png').convert('L'), dtype=np.float32)
    # Northern central snow/ice terrain must remain relief, while the painted
    # atmospheric cloud bank in the upper-right edge must be masked strongly.
    snowy_terrain=cloud[0:250,650:1100].mean()
    atmospheric_bank=cloud[0:220,1850:2048].mean()
    assert snowy_terrain < 12
    assert atmospheric_bank > 90
