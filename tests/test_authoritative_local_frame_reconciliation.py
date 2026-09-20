from cad_engine.plan_segmentation import _plans_from_authoritative_profiles


def test_confirmed_level_identity_uses_unique_local_frame_at_title_anchor():
    profiles=[{
        "name":"تیپ طبقات اول تا پنجم",
        "region_bounds":[3608,-9897,7587,137],
        "title_point":[3713.68,-5246.70],
        "level_detection_status":"confirmed",
        "roof":False,
    }]
    frames=[
        {"plan_id":"PLAN-08","bounds":[3684.18,-5250.30,3705.18,-5219.53]},
        {"plan_id":"PLAN-09","bounds":[3705.18,-5250.30,3726.18,-5219.53]},
    ]
    plans=_plans_from_authoritative_profiles(profiles,frames)
    assert plans[0]["bounds"]==frames[1]["bounds"]
    assert plans[0]["source"]=="sealed_browser_identity_local_print_frame"
    assert plans[0]["level"]=="تیپ طبقات اول تا پنجم"


def test_ambiguous_or_missing_title_anchor_keeps_sealed_region_bounds():
    profile={
        "name":"طبقه اول","region_bounds":[0,0,100,100],
        "title_point":[10,10],"level_detection_status":"confirmed",
    }
    overlapping=[{"bounds":[0,0,20,20]},{"bounds":[5,5,25,25]}]
    plans=_plans_from_authoritative_profiles([profile],overlapping)
    assert plans[0]["bounds"]==[0.0,0.0,100.0,100.0]
    assert plans[0]["source"]=="sealed_browser_level_profile"


def test_authoritative_floor_retains_only_local_non_design_frames_for_ownership():
    profile={
        "name":"طبقه همکف","region_bounds":[0,0,100,100],
        "title_point":[12,12],"level_detection_status":"confirmed","roof":False,
    }
    frames=[
        {"plan_id":"LOCAL-FLOOR","bounds":[0,0,30,20],"mechanical_role":"PRIMARY_FLOOR"},
        {"plan_id":"LOCAL-SECTION","bounds":[30,0,60,20],"mechanical_role":"EXCLUDE"},
        {"plan_id":"LOCAL-DUP","bounds":[60,0,90,20],"mechanical_role":"DUPLICATE_REFERENCE"},
        {"plan_id":"LOCAL-ROOF","bounds":[0,20,30,40],"mechanical_role":"ROOF_SUPPORT"},
    ]

    plans=_plans_from_authoritative_profiles([profile],frames)

    assert [row["plan_id"] for row in plans] == ["PLAN-AUTH-01","LOCAL-SECTION","LOCAL-DUP","LOCAL-ROOF"]
    assert plans[0]["bounds"] == frames[0]["bounds"]
    assert all(row["source"] == "local_excluded_frame_ownership_evidence" for row in plans[1:])
    assert plans[-1]["mechanical_role"] == "EXCLUDE"
    assert plans[-1]["roof_view_role"] == "REJECTED_LOCAL_ROOF_OWNERSHIP_ONLY"
