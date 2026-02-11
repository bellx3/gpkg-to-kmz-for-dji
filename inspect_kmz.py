import sys, zipfile, xml.etree.ElementTree as ET
from pathlib import Path
# Allow passing KMZ path as first argument; fallback to a default
p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(r'd:\00_미션저작도구\output\하예동1751-5.kmz')
with zipfile.ZipFile(p,'r') as z:
    names = z.namelist()
    print('KMZ:', p.name)
    print('KMZ contents:', names)
    kml = z.read('template.kml')
    wpml = z.read('waylines.wpml')
    root_kml = ET.fromstring(kml)
    NS={'kml':'http://www.opengis.net/kml/2.2','wpml':'http://www.dji.com/wpmz/1.0.6'}
    def find_text(xpath):
        el = root_kml.find(xpath, NS)
        return el.text if el is not None else None
    print('KML ellipsoidHeight:', find_text('.//kml:Folder/kml:Placemark/wpml:ellipsoidHeight'))
    print('KML height:', find_text('.//kml:Folder/kml:Placemark/wpml:height'))
    print('KML globalShootHeight:', find_text('.//kml:Folder/wpml:waylineCoordinateSysParam/wpml:globalShootHeight'))
    print('KML surfaceRelativeHeight:', find_text('.//kml:Folder/wpml:waylineCoordinateSysParam/wpml:surfaceRelativeHeight'))
    print('KML margin:', find_text('.//kml:Folder/kml:Placemark/wpml:margin'))
    print('KML overlap camera H:', find_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapH'))
    print('KML overlap camera W:', find_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoCameraOverlapW'))
    print('KML overlap lidar H:', find_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoLidarOverlapH'))
    print('KML overlap lidar W:', find_text('.//kml:Folder/kml:Placemark/wpml:overlap/wpml:orthoLidarOverlapW'))
    print('KML autoFlightSpeed:', find_text('.//kml:Folder/wpml:autoFlightSpeed'))
    print('KML globalTransitionalSpeed:', find_text('.//wpml:missionConfig/wpml:globalTransitionalSpeed'))
    print('KML takeOffSecurityHeight:', find_text('.//wpml:missionConfig/wpml:takeOffSecurityHeight'))
    # WPML
    root_wpml = ET.fromstring(wpml)
    def find_wp(xpath):
        el = root_wpml.find(xpath, NS)
        return el.text if el is not None else None
    print('WPML globalShootHeight:', find_wp('.//wpml:waylineCoordinateSysParam/wpml:globalShootHeight'))
    print('WPML surfaceRelativeHeight:', find_wp('.//wpml:waylineCoordinateSysParam/wpml:surfaceRelativeHeight'))
    print('WPML autoFlightSpeed:', find_wp('.//wpml:autoFlightSpeed'))
    print('WPML globalTransitionalSpeed:', find_wp('.//wpml:missionConfig/wpml:globalTransitionalSpeed'))
    print('WPML takeOffSecurityHeight:', find_wp('.//wpml:missionConfig/wpml:takeOffSecurityHeight'))
    # WPML executeHeight summary
    ex_elems = root_wpml.findall('.//kml:Folder/kml:Placemark/wpml:executeHeight', NS)
    ex_vals = [el.text for el in ex_elems]
    print('WPML executeHeight count:', len(ex_vals))
    print('WPML executeHeight sample:', ex_vals[:5])