"""!@package ssurgolib.featurequery
    
@brief Make feature queries against USDA Soil Data Mart OGC web service interface

This software is provided free of charge under the New BSD License. Please see
the following license information:

Copyright (c) 2013, University of North Carolina at Chapel Hill
All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:
    * Redistributions of source code must retain the above copyright
      notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above copyright
      notice, this list of conditions and the following disclaimer in the
      documentation and/or other materials provided with the distribution.
    * Neither the name of the University of North Carolina at Chapel Hill nor the
      names of its contributors may be used to endorse or promote products
      derived from this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF NORTH CAROLINA AT CHAPEL HILL
BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR 
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT 
LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.


@author Brian Miles <brian_miles@unc.edu>
"""
import os
import sys
import errno
import xml.sax

from owslib.wfs import WebFeatureService

from spatialdatalib.utils import calculateBoundingBoxAreaSqMeters
from spatialdatalib.utils import tileBoundingBox
from attributequery import getParentMatKsatTexturePercentClaySiltSandForComponentsInMUKEYs
from attributequery import computeWeightedAverageKsatClaySandSilt
from attributequery import joinSSURGOAttributesToFeaturesByMUKEY
from saxhandlers import SSURGOFeatureHandler       

MAX_SSURGO_EXTENT = 10000000000 # 10,100,000,000 sq. meters
MAX_SSURGO_EXTENT = MAX_SSURGO_EXTENT / 10


def getMapunitFeaturesForBoundingBox(outputDir, bbox, \
                                     mapunitExtended=False, tileBbox=False):
    """!Query USDA Soil Data Mart for SSURGO Mapunit features with a given bounding box.
        Features will be written to one or more GML files, one file for each bboxTile tile,
        stored in the specified output directory. The filename will be returned as a string.
        Will fetch SSURGO tabular data (see ssurgolib.attributequery.attributeList for a list
        of attributes) and join those data to the features in the GML files(s).
    
        @note Will silently exit if features already exist.
    
        @param outputDir String representing the absolute/relative path of the directory into which features should be written
        @param bbox A dict containing keys: minX, minY, maxX, maxY, srs, where srs='EPSG:4326'
        @param mapunitExtended True if extended mapunit features should be fetched.
        @param tileBoundingBox True if bounding box should be tiled if extent exceeds featurequery.MAX_SSURGO_EXTENT
        
        @return A list of strings representing the name of the GML file(s) to which the mapunit features were saved.
        
        @exception IOError if output directory is not a directory
        @exception IOError if output directory is not writable
        @exception Exception if bounding box area is greater than MAX_SSURGO_EXTENT
    """
    if not os.path.isdir(outputDir):
        raise IOError(errno.ENOTDIR, "Output directory %s is not a directory" % (outputDir,))
    if not os.access(outputDir, os.W_OK):
        raise IOError(errno.EACCES, "Not allowed to write to output directory %s" % (outputDir,))
    outputDir = os.path.abspath(outputDir)

    if mapunitExtended:
        typeName = 'MapunitPolyExtended'
    else:
        typeName = 'MapunitPoly'

    if tileBbox:
        bboxes = tileBoundingBox(bbox, MAX_SSURGO_EXTENT)
        sys.stderr.write("Dividing bounding box %s into %d tiles\n" % (str(bbox), len(bboxes)))
    else:
        if calculateBoundingBoxAreaSqMeters(bbox) > MAX_SSURGO_EXTENT:
            raise Exception("Bounding box area is greater than %f sq. meters" % (MAX_SSURGO_EXTENT,))
        bboxes = [bbox]
    
    gmlFiles = []
    
    for bboxTile in bboxes:
        minX = bboxTile['minX']; minY = bboxTile['minY']; maxX = bboxTile['maxX']; maxY = bboxTile['maxY']
        bboxLabel = str(minX) + "_" + str(minY) + "_" + str(maxX) + "_" + str(maxY)
    
        gmlFilename = "%s_bbox_%s-attr.gml" % (typeName, bboxLabel)
        gmlFilepath = os.path.join(outputDir, gmlFilename)
    
        if not os.path.exists(gmlFilepath):
            sys.stderr.write("Fetching SSURGO data for sub bboxTile %s\n" % bboxLabel)
        
            wfs = WebFeatureService('http://SDMDataAccess.nrcs.usda.gov/Spatial/SDMWGS84Geographic.wfs', version='1.0.0')
            filter = "<Filter><BBOX><PropertyName>Geometry</PropertyName> <Box srsName='EPSG:4326'><coordinates>%f,%f %f,%f</coordinates> </Box></BBOX></Filter>" % (minX, minY, maxX, maxY)
            gml = wfs.getfeature(typename=(typeName,), filter=filter, propertyname=None)
    
            # Write intermediate GML to a file
            intGmlFilename = "%s_bbox_%s.gml" % (typeName, bboxLabel)
            intGmlFilepath = os.path.join(outputDir, intGmlFilename)
            out = open(intGmlFilepath, 'w')
            out.write(gml.read())
            out.close()
            
            # Parse GML to get list of MUKEYs
            gmlFile = open(intGmlFilepath, 'r')
            ssurgoFeatureHandler = SSURGOFeatureHandler()
            xml.sax.parse(gmlFile, ssurgoFeatureHandler)
            gmlFile.close()
            mukeys = ssurgoFeatureHandler.mukeys
            
            # Get attributes (ksat, texture, %clay, %silt, and %sand) for all components in MUKEYS
            attributes = getParentMatKsatTexturePercentClaySiltSandForComponentsInMUKEYs(mukeys)
            
            # Compute weighted average of soil properties across all components in each map unit
            avgAttributes = computeWeightedAverageKsatClaySandSilt(attributes)
            
            # Join map unit component-averaged soil properties to attribute table in GML file
            gmlFile = open(intGmlFilepath, 'r')
            joinedGmlStr = joinSSURGOAttributesToFeaturesByMUKEY(gmlFile, typeName, avgAttributes)
            gmlFile.close()
            
            # Write Joined GML to a file
            out = open(gmlFilepath, 'w')
            out.write(joinedGmlStr)
            out.close()
            
            # Delete intermediate GML file
            os.unlink(intGmlFilepath)
        
        gmlFiles.append(gmlFilename)
    
    # TODO: join tiled data if tileBbox
        
    return gmlFiles
    
    