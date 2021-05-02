#!/usr/bin/env python
# coding: utf-8

# # Converting California PPOD spreadsheet into RDF
# 
# This notebook takes Patrick Huber's Google Sheets spreadsheets for managing the California 
# conservation-related PPOD information and converts it into RDF, outputting it in turtle format.
# 
# 

import gspread
import pandas as pd
import binascii
import rdflib
from pprint import pprint
from oauth2client.service_account import ServiceAccountCredentials

##### Data #####

# ### Incorporating our linked identifiers
# 
# We want the following:
# 
# * The rdf:type of each of the major sheets i.e. for each instance listing. This will be to an agreed-upon term (e.g. foaf:Organization)
# * For the vocabs, they will all share the base URI for the ttl file itself, but might want to use our 24-bit hash thing for each term. Something like CaPPOD:vocab_A24D83. But the hash should concatenate the vocab name and the term name
# * For all the columns in each sheet / dataframe, look up if we have any equivalent in PPOD / the OKN work, and use that terminology for those properties.


# Some namespaces
auxprefix = 'http://asi.ice.ucdavis.edu/sustsource/schemas/CA_PPODterms.ttl#' # needs to change!
rdfsuri = "http://www.w3.org/2000/01/rdf-schema#"
rdfuri = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"



# The URIs for the major types in the workbook. 
# Not sure about the guidelines/mandates one but this will do until 
# I work up a more elaborate ontology for it.
PPODrefs = {'Organizations': 'http://xmlns.com/foaf/0.1/Organization',
            'Projects': 'http://vivoweb.org/ontology/core#Project',
            'Programs': 'http://vivoweb.org/ontology/core#Program',
            'People': 'http://xmlns.com/foaf/0.1/Person',
            'Guidelines_Mandates':'http://www.sdsconsortium.org/schemas/sds-okn.owl#BestPracticesAndMandates',
            'Datasets': 'http://vivoweb.org/ontology/core#Dataset',
            'Tools': 'http://www.sdsconsortium.org/schemas/sds-okn.owl#Tool',
            'Issues (Integrated)': 'http://asi.ice.ucdavis.edu/sustsource/schemas/sustsource.owl#IntegratedIssue',
            'Issues (Component)': 'http://asi.ice.ucdavis.edu/sustsource/schemas/sustsource.owl#ComponentIssue'
           }



# We now want dictionaries for all our lists of properties associated with each major type.
# These will give a tuple of (Data "d" or Object property "o" (internal), "u" object property (URL), "v" - object property internal vocab) 
# URI for property, label string for property, either name of dictionary (string) for 'v' or hash code prefix for 'o'),
# then 's' or 'm' for comma-delimiting string split
# to repeat: ([d|o|v|u], property URI, property label, string for dictionary name or prefix, '[s|m]')

# Organization predicates dictionary
orgpred = {"Organization": ('d', 'http://purl.org/dc/terms/title', 'title', '', 's'),
            "Alias": ('d', 'http://www.w3.org/2004/02/skos/core#altLabel', 'alias', '', 's'),
            "isPartOf": ('o', 'http://purl.org/dc/terms/isPartOf', 'is part of', 'org','m'),
          "isMemberOf": ('o', 'http://www.w3.org/ns/org#memberOf', 'is member of', 'org', 'm'),
           # for county, will change the URI at some point
          "County": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inCounty', 'in county', 'countydict', 'm'),
           "Ecoregion": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inEcoregion', 'in ecoregion', 'ecoregiondict','m'),
          "hasOrgType": ('v', 'http://www.w3.org/ns/org#classification', 'organization type', 'orgtypedict', 'm'),
          "Partners": ('o', 'http://vivoweb.org/ontology/core#hasCollaborator', 'has partner', 'org', 'm'),
            "Funding": ('o', 'http://purl.org/cerif/frapo/isFundedBy', 'is funded by', 'org','m'),
           "hasOrgActivity": ('v', 'http://purl.obolibrary.org/obo/RO_0000056', 'participates in','orgactivitydict', 'm'),
           "Issues": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'), # need to agglom comp and int issues
           "URL": ('u', 'http://dev.poderopedia.com/vocab/hasURL', 'has URL', '', 'm'),
           "Contact": ('d', 'http://vivoweb.org/ontology/core#contactInformation', 'contact', '','s'),
           # taxa should be an object property at some point, but for assume content is a string
           "Taxa": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#taxa', 'taxa', '','m'),
           "Land Cover - CWHR": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#habitatType', 'habitat type', 'habtypedict', 'm'), # need to build this
           "Ecological Process": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#ecologicalProcess', 'ecological process', '','s'),
           "GM_Name": ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#GM_Name', 'guideline/mandate name', 'gmt', 'm')
          }
           
        


# Project predicates dictionary
projpred = {"Project": ('d', 'http://xmlns.com/foaf/0.1/Project', 'project', '','s'),
            "Alias": ('d', 'http://www.w3.org/2004/02/skos/core#altLabel', 'alias', '', 's'),
            "isPartOf": ('o', 'http://purl.org/dc/terms/isPartOf', 'is part of', 'prj','m'),
            "ProjType": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#projType', 'project type', 'projtypedict', 'm'),
            "ProjProg": ('o', 'http://purl.obolibrary.org/obo/BFO_0000066', 'occurs in', 'prg','m'),
            "Organization (Lead)": ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#leadOrg', 'lead organization', 'org', 'm'),
            "Organization (Funding)": ('o', 'http://vivoweb.org/ontology/core#fundingAgentFor', 'funding organization', 'org', 'm'),
            "OrgFundProg": ('o', 'http://vivoweb.org/ontology/core#hasFundingVehicle', 'funding provided via', 'prg','m'),
            "Lead Individual": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#leadIndividual', 'lead individual', '', 's'),
            "Partners": ('o', 'http://vivoweb.org/ontology/core#affiliatedOrganization', 'partner organization', 'org', 'm'),
            "Location": ('d', 'http://purl.obolibrary.org/obo/RO_0001025', 'located in', '', 's'),
            "County": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inCounty', 'in county', 'countydict', 'm'),
            "Ecoregion": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inEcoregion', 'in ecoregion', 'ecoregiondict', 'm'),
            "Watershed": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inWatershed', 'in watershed', '', 's'),
            "Issues": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'),
            "ProjDetails": ('u', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#projDetails', 'project details', '', 's'),
            "Indicators": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#hasIndicator', 'has indicator', '', 's'),
            "inDataset": ('o', 'http://purl.obolibrary.org/obo/RO_0002352', 'input of', 'dts', 'm'),
            "outDataset": ('o', 'http://purl.obolibrary.org/obo/RO_0002353', 'output of', 'dts', 'm'),
            "Strategies": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#hasStrategy', 'has strategy', '', 'm'),
            "URL": ('u', 'http://dev.poderopedia.com/vocab/hasURL', 'has URL', '', 'm'),
            "Taxa": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#taxa', 'taxa', '', 'm'),
            "Land Cover - CWHR": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#habitatType', 'habitat type', 'habtypedict', 'm'),
            "Ecological Process": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#ecologicalProcess', 'ecological process', '', 's'),
            "Start Year": ('d', 'http://dbpedia.org/ontology/startYear', 'startYear', '', 's'),
            "End Year": ('d', 'http://dbpedia.org/ontology/endYear', 'endYear', '', 's'),
            "Funding": ('o', 'http://purl.org/cerif/frapo/isFundedBy', 'isFundedBy', 'org','m'),
            "Latitude": ('d', 'https://www.w3.org/2003/01/geo/wgs84_pos#lat', 'latitude', '', 's'),
            "Longitude": ('d', 'https://www.w3.org/2003/01/geo/wgs84_pos#long', 'longitude', '', 's'),
            "FSL doc": ('u', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSLdoc', 'FSL doc', '', 's'),
            "Use Case (Meat)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseMeat', 'use case: meat', '', 's'),
            "Use Case (EPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseEPA', 'use case: EPA', '', 's'),
            "Use Case (JPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseJPA', 'use case: JPA','', 's')    
}

# program predicates dictionary
progpred = {
            "Program": ('d', 'http://vivoweb.org/ontology/core#Program', 'program', '', 's'),    
            "Alias":   ('d', 'http://www.w3.org/2004/02/skos/core#altLabel', 'alias', '', 's'),
            "ProgType": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#progType', 'program yype', 'progtypedict', 'm'),
            "Organization": ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#leadOrg', 'lead organization', 'org', 'm'),
            "Partners": ('o', 'http://vivoweb.org/ontology/core#affiliatedOrganization', 'partner organization', 'org', 'm'),
            "Issues": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'),
            "Lead Individual": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#leadIndividual', 'lead individual', '', 's'),
            "GM_Name": ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#GM_Name', 'guideline/mandate name', 'gmt', 'm'),
            "County": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inCounty', 'in county', 'countydict', 'm'),
            "Ecoregion": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inEcoregion', 'in ecoregion', 'ecoregiondict', 'm'),
            "URL": ('u', 'http://dev.poderopedia.com/vocab/hasURL', 'has URL', '', 'm'),
            "Taxa": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#taxa', 'taxa', '', 'm'),
            "Use Case (Meat)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseMeat', 'use case: meat', '', 's'),
            "Use Case (EPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseEPA', 'use case: EPA', '', 's'),
            "Use Case (JPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseJPA', 'use case: JPA', '', 's'),
            "Use Case (SCAG)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseSCAG', 'use case: SCAG', '', 's'),
    
            
}


personpred = {
            "Full Name": ('d', 'http://xmlns.com/foaf/0.1/name', 'full name', '', 's'),
            "Last Name": ('d', 'http://xmlns.com/foaf/0.1/lastName', 'last name', '', 's'),
            "First Name": ('d', 'http://xmlns.com/foaf/0.1/firstName', 'first name', '', 's'),
            "Email": ('d', 'http://xmlns.com/foaf/0.1/mbox', 'email', '', 's'),
            "Phone": ('d', 'http://xmlns.com/foaf/0.1/phone', 'phone', '', 's'),
            "Issues": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'),
            "Notes": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000243', 'note', '', 's'),
            "usecaseConservation": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseCons', 'use case: Conservation', '', 's'),
            "usecaseMeat": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseMeat', 'use case: meat', '', 's'),
            "usecaseSac": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseSac', 'use case: Sacramento', '', 's'),
            "usecaseSCAG": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseSCAG', 'use case: SCAG', '', 's'),
            "usecaseEcuador": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseEcuador', 'use case: Ecuador', '', 's'),
            "usecaseBayAreaRAMP": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseBayAreaRAMP', 'use case: Bay Area RAMP', '', 's'),

}



personorgpred = {
            "Full Name": ('o', 'http://purl.obolibrary.org/obo/RO_0000057', 'has participant', 'per', 's'),
            "Organization": ('o', 'http://purl.obolibrary.org/obo/RO_0000081', 'role of', 'org', 's'),
            "Position (Verbatim)": ('d', 'http://purl.org/dc/terms/title', 'title', '', 'd'),
            "Position (Type)": ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#positionType', 'position type', 'positiontypedict', 'm'),
            "Year (Start)": ('d', 'http://dbpedia.org/ontology/startYear', 'startYear', '', 'd' ),
            "Year (End)": ('d', 'http://dbpedia.org/ontology/endYear', 'endYear',  '', 'd')
}



personprojpred = {
            "Full Name": ('o', 'http://purl.obolibrary.org/obo/RO_0000057', 'has participant', 'per', 's'),
            "Project": ('o', 'http://purl.obolibrary.org/obo/RO_0002331', 'involved in', 'prj', 's'),
            #"ProjRole": ('o', 'http://purl.obolibrary.org/obo/RO_0000087', 'has role', 'projroledict', 's'),
            "ProjRole": ('d', 'http://purl.obolibrary.org/obo/RO_0000087', 'has role', '', 's'),

}


personprogrampred = {
            "Full Name": ('o', 'http://purl.obolibrary.org/obo/RO_0000057', 'has participant', 'per', 's'),
            "Program": ('o', 'http://purl.obolibrary.org/obo/RO_0002331', 'involved in', 'prg', 's'),
            "Role": ('d', 'http://purl.obolibrary.org/obo/RO_0000087', 'has role', '', 's'),
            #"Role": ('v', 'http://purl.obolibrary.org/obo/RO_0000087', 'has role', 'progroledict', 's'),
            "Role (Type)": ('u', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#roleType', 'role type', '', 's'), # not sure what Patrick is doing with this.
            "Year (Start)": ('d', 'http://dbpedia.org/ontology/startYear', 'start year', '', 's'),
            "Year (End)": ('d', 'http://dbpedia.org/ontology/endYear', 'end year', '', 's')
}


guidelinespred = {
            "GM_Name": ('d', 'http://purl.org/dc/terms/title', 'Name', '', 's'),
            "Alias": ('d', 'http://www.w3.org/2004/02/skos/core#altLabel', 'alias', '', 's'),
            "GMType": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#gmType', 'guideline/mandate type', 'gmtypedict', 'm'),
            "Year": ('d', 'http://purl.org/dc/terms/date', 'date', '', 's'), 
            "Issues": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'),
            "GovLevel": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#govLevel', 'government level', 'govleveldict', 'm'),
            "Counties": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inCounty', 'in county', 'countydict', 'm'),
            "Ecoregions": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#inEcoregion', 'in ecoregion', 'ecoregiondict', 'm'),
            "URL": ('u', 'http://dev.poderopedia.com/vocab/hasURL', 'has URL', '', 's'),
            "Taxa": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#taxa', 'taxa', '', 's'),
            "Land Cover - CWHR": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#habitatType', 'habitat type', 'habtypedict', 'm'),
            "Ecological Process": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#ecologicalProcess', 'ecological process', '', 's'),
            "Use Case (Meat)":('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseMeat', 'use case: meat', '', 's'),
            "Use Case (EPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseEPA', 'use case: EPA', '', 's')
    
}

# this has different logic! Patrick is basically encoding triples here, and the dictionary below
# is the lookup for the second column
orggmpred = {
            "Created": ('o', 'http://iflastandards.info/ns/fr/frbr/frbrer/P2008', 'creator of'), # oh look, FRBRer!
            "Was Created By": ('o', 'http://iflastandards.info/ns/fr/frbr/frbrer/P2007', 'was created by'),
            "Implements": ('o',  'https://w3id.org/dingo#implements', 'implements'), # DINGO is (another) projects and grants ontology 
            "Mandates": ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#mandates', 'mandates'),
            "Funds Established By": ('o', 'http://vivoweb.org/ontology/core#hasFundingVehicle', 'has funding vehicle'),  
}

# somewhat different logic for this table as well. columns C, D, E in this table form a class that
# whose instances the GMs in column A point to with predicate in column B. The entries in this 
# dictionary are for columns C, D, and E
orgprojgmpred = {
            "Organization": ('o', 'http://purl.obolibrary.org/obo/RO_0000057', 'has participant', 'org', 's'),
            "OrgProjRelation": ('o', 'http://purl.obolibrary.org/obo/RO_0000087', 'has role', 'orgprojrelationdict', 's'),
            "Project": ('o', 'http://purl.obolibrary.org/obo/RO_0002331', 'involved in', 'prj', 's'),
}

datasetpred = {
            "Name":  ('d', 'http://purl.org/dc/terms/title', 'title', '', 's'),
            "Organization (Created By)": ('o', 'http://iflastandards.info/ns/fr/frbr/frbrer/P2007', 'was created by', 'org', 's'),
            "Issues": ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'),
            "GM_Name":  ('o', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#mandatedBy', 'mandated by', 'gmt', 'm'),
            "URL":  ('u', 'http://dev.poderopedia.com/vocab/hasURL', 'has URL', '', 's'),
            "Use Case (Meat)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseMeat', 'use case: meat', '', 's'),
            "Use Case (JPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseJPA', 'use case: JPA', '', 's'),
            "Use Case (EPA)": ('d', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#usecaseEPA', 'use case: EPA', '', 's')
    
}


toolpred = {
            "Tool": ('d', 'http://purl.org/dc/terms/title', 'title', '', 's'),
            "Alias": ('d', 'http://www.w3.org/2004/02/skos/core#altLabel', 'alias', '', 's'),
            "Organization":  ('o', 'http://iflastandards.info/ns/fr/frbr/frbrer/P2007', 'was created by', 'org', 's'),
            "Issues":  ('v', 'http://asi.ice.ucdavis.edu/sustsource/schemas/fsisupp.owl#FSI_000239', 'related sustainability issue', 'issuedict', 'm'),
            "inDataset": ('o', 'http://purl.obolibrary.org/obo/RO_0002233', 'has input', 'dts', 'm'),
            "outDataset": ('o', 'http://purl.obolibrary.org/obo/RO_0000087', 'has output', 'dts', 'm'),
            "ToolDetails": ('u', 'http://purl.org/dc/terms/references', 'references', '', 's'),
            "URL": ('u', 'http://dev.poderopedia.com/vocab/hasURL', 'has URL', '', 's')
}




##### Functions #####

# Let's create a minihash function for unique identifiers. I figure 24 bits is big enough (6 hex digits).
# I'm just going to use crc32 and truncate the last two digits.
def makeid(s):
    hexid = hex(binascii.crc32(bytes(s.encode("utf-8"))))[2:8] 
    return hexid

# I figure I will use this as identifier suffixes for all these text names that are too long to abbreviate. E.g. 'Yuba County Resource Conservation District' becomes `CaPPOD:org_fb822f` using the `makeid` function.

# Return a dictionary giving the URI for a particular vocabulary term
def makevocabdict(vocabdframe, vocabdfstr, auxprefix, prefixstr):
    vrole = vocabdframe[vocabdfstr]
    vdict = {}
    for i in range(vrole.shape[0]):
        s = vrole[i]
        if len(s) > 0:
            vdict.update({s : auxprefix + prefixstr + "_"  + makeid(s)})
    return vdict


# add a triple (or multiples maybe) to the graph g based on details in describing predicate
def addtriple(g, prdetails, subjval, cellval, subjectstr):
    subj =  rdflib.URIRef(subjval)
    if cellval == 'All':
        if prdetails[3] == 'countydict':
            cellval = ','.join(countydict.keys())    
        elif prdetails[3] == 'ecoregiondict':
            cellval = ','.join(ecoregiondict.keys())
    if prdetails[4] == 'm':
        celllist = [s.strip() for s in cellval.split(',')]
    else:
        celllist = [cellval]
    for cell in celllist:
        if prdetails[0] == 'd':
            pred = rdflib.URIRef(prdetails[1])
            if 'usecase' in prdetails[1]:
                if cell == 'X' or cell == 'x':
                    obj = rdflib.Literal(True, datatype = rdflib.namespace.XSD.boolean)
            else:
                obj = rdflib.Literal(cell)
            g.add((subj, pred, obj))
        elif prdetails[0] == 'v':
            try:
                obj = rdflib.URIRef(eval(prdetails[3])[cell])
                pred = rdflib.URIRef(prdetails[1])
                g.add((subj, pred, obj))
            except KeyError:
                print(subjectstr + ": " + cell + " not in " + prdetails[3])
                pass
        elif prdetails[0] == 'o':
            pred = rdflib.URIRef(prdetails[1])
            obj = rdflib.URIRef( auxprefix + prdetails[3] + "_" + makeid(cell))
            g.add((subj, pred, obj))
        elif prdetails[0] == 'u':
            pred = rdflib.URIRef(prdetails[1])
            obj = rdflib.URIRef(cell)
            g.add((subj, pred, obj))



##### Actions #####



# get authorization to access Google Sheets
# use creds to create a client to interact with the Google Drive API
scope = ['https://spreadsheets.google.com/feeds']
creds = ServiceAccountCredentials.from_json_keyfile_name('fsl-data-access-8731857cb6f9.json', scope)
gssclient = gspread.authorize(creds)
gsworkbook = gssclient.open_by_url('https://docs.google.com/spreadsheets/d/1k_BeTRklXz1aAh25DyYs1TIY7Okfa3jh6YJC6PQTUiE')


# get pointers to all the relevant sheets
vocab_sheet = gsworkbook.worksheet('Vocabularies')
organizations_sheet = gsworkbook.worksheet('Organizations')
projects_sheet = gsworkbook.worksheet('Projects')
program_sheet = gsworkbook.worksheet('Programs')
people_sheet = gsworkbook.worksheet('People')
peopleorgs_sheet = gsworkbook.worksheet('PeopleOrg')
peopleproj_sheet = gsworkbook.worksheet('PeopleProj')
peopleprogram_sheet = gsworkbook.worksheet('PeopleProgram')
guidelines_sheet = gsworkbook.worksheet('Guidelines_Mandates')
orggm_sheet = gsworkbook.worksheet('OrgGM')
orgprojgm_sheet = gsworkbook.worksheet('OrgProjGM')
datasets_sheet = gsworkbook.worksheet('Datasets')
tools_sheet = gsworkbook.worksheet('Tools')
futureresources_sheet = gsworkbook.worksheet('Future Resources')
intissues_sheet = gsworkbook.worksheet('Issues (Integrated)')
compissues_sheet = gsworkbook.worksheet('Issues (Component)')

# convert these to data frames
vocabdf = pd.DataFrame(vocab_sheet.get_all_records())
orgdf = pd.DataFrame(organizations_sheet.get_all_records())
projdf = pd.DataFrame(projects_sheet.get_all_records())
progdf = pd.DataFrame(program_sheet.get_all_records())
peopledf = pd.DataFrame(people_sheet.get_all_records())
peopleorgdf = pd.DataFrame(peopleorgs_sheet.get_all_records())
peopleprojdf = pd.DataFrame(peopleproj_sheet.get_all_records())
peopleprogramdf = pd.DataFrame(peopleprogram_sheet.get_all_records())
guidelinesdf = pd.DataFrame(guidelines_sheet.get_all_records())
orggmdf = pd.DataFrame(orggm_sheet.get_all_records())
orgprojgmdf = pd.DataFrame(orgprojgm_sheet.get_all_records())
datasetdf = pd.DataFrame(datasets_sheet.get_all_records())
tooldf = pd.DataFrame(tools_sheet.get_all_records())
intissuedf = pd.DataFrame(intissues_sheet.get_all_records())
compissuedf = pd.DataFrame(compissues_sheet.get_all_records())



# Create dictionary of predicate URIs as keys and their labels as values
predlabeldict = {}
predsbyclasslist = [orgpred, projpred, progpred, personpred, personorgpred, personprojpred, personprogrampred, guidelinespred,
           orggmpred, orgprojgmpred, datasetpred, toolpred]
for predsbyclass in predsbyclasslist:
    for pred0 in predsbyclass.keys():
        pred0val = predsbyclass[pred0]
        pred0URI = pred0val[1]
        pred0label = pred0val[2]
        if pred0URI not in predlabeldict: # the first in is the winner
            predlabeldict[pred0URI] = pred0label




# #### Vocabularies
# 
# The first sheet (vocab_sheet) is a listing of vocabularies in use. Each column is a separate vocabulary. Some of
# these (e.g. issues) we've already established URIs for (though I might want to port them, but that's another story), others are new terms. How should I handle all these?
# Each of these terms should get loaded into a dictionary, probably a separate one for each column. 
# Both County and Ecoregions have an "all" term, which is best handled by some special code dumping in all 58 counties e.g. 

# For the issues, we want to use our established terms. The intissues and compissues sheets gives the suffixes for these. 



intissuedict = {}
intissueprefix = "http://asi.ice.ucdavis.edu/sustsource/schemas/sustsource.owl#"

for i in range(intissuedf.shape[0]):
    #print(intissuedf.iloc[i,0], intissuedf.iloc[i,1])
    intissuedict.update( {intissuedf.iloc[i,1] : intissueprefix + intissuedf.iloc[i,0] })


# Now for the component issues
compissuedict = {}
compissueprefix = "http://asi.ice.ucdavis.edu/sustsource/schemas/sustsourceindiv.rdf#"
for i in range(compissuedf.shape[0]):
    compissuedict.update( {compissuedf.iloc[i,1] : compissueprefix + compissuedf.iloc[i,0] })



# we want to merge these two dictionaries
issuedict = {**compissuedict , **intissuedict} 


# #### Counties
# After some search, have opted to use Wikidata URIs for the California counties. I grabbed these from Wikidata using their SPARQL query interface.
counties_wd = pd.read_csv('CACounties_WD.csv')


countydict = {}
for i in range(counties_wd.shape[0]):
    countydict.update( {counties_wd.iloc[i,1] : counties_wd.iloc[i,0] })




# For the rest of these vocabulary columns I'm going to use my minihash function.

# Ecoregions
ecoregions = vocabdf['Ecoregion_USDA']

ecoregiondict = {}
for i in range(1, ecoregions.shape[0]):
    s = ecoregions[i]
    if len(s) > 0:
        ecoregiondict.update( {s : auxprefix + "eco_" + makeid(s)})
        
    

# habitat type, use CWHR here
cwhrdf = pd.read_csv('CWHR_Habitat_Lookup_Table.csv')
habtypedict = {}
for i in range(cwhrdf.shape[0]):
    habtypedict.update( {cwhrdf.iloc[i,0] : 'http://asi.ice.ucdavis.edu/sustsource/schemas/CA_PPODterms.ttl#whr_' + cwhrdf.iloc[i,0] })

orgtypedict = makevocabdict(vocabdf, 'OrgType', auxprefix, 'oty')
orgactivitydict = makevocabdict(vocabdf, 'OrgActivity', auxprefix, 'oac')
projtypedict = makevocabdict(vocabdf, 'ProjType', auxprefix, 'pjt')
progtypedict = makevocabdict(vocabdf, 'ProgType', auxprefix, 'pgt')
gmtypedict = makevocabdict(vocabdf, 'GMType', auxprefix, 'gmn')
govleveldict = makevocabdict(vocabdf, 'GovLevel', auxprefix, 'gvl')
positiontypedict = makevocabdict(vocabdf, 'PositionType', auxprefix, 'pst')
projroledict = makevocabdict(vocabdf, 'PeopleProjRole', auxprefix, 'prl')
orggmrelationdict = makevocabdict(vocabdf, 'orgGMRelation', auxprefix, 'pst') # is prefix correct?
# orgGMRelation - might handle this in different manner - these are properties. But I'll create the dict for now.
# #### Actually, the above is redundant
orgprojrelationdict = makevocabdict(vocabdf, 'orgProjRelation', auxprefix, 'prl') 
# orgProjRelation - this may be redundant as well, but for completeness....





# #### Refining things
# Each cell of the sheets can refer to 4 different things I think. These will have different treatments. They can be:
# * Literals. Just add them as strings
# * References to other objects in this spreadsheet system.
# * References to outside URLs
# * References to vocabularies. These are stored in this script as dictionaries.
# 
# We will need to notate which of these 4 things goes in each cell (expand from 'd', 'o' to 4 things). Also we want to notate which of these entries we break apart into multiples if comma-separated. We also may need to know the prefix for the referenced entity in my hashcode system.



# ### Making a graph
# 
# I think we're ready to start creating some rdf!



# Initialize the in-memory RDF graph
g = rdflib.Graph()


# the first step is to get vocabularies loaded, in particular creating rdfs:labels for the entries





for k in ecoregiondict.keys():
    subj = rdflib.URIRef(ecoregiondict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))


for k in issuedict.keys():
    subj = rdflib.URIRef(issuedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))



for k in countydict.keys():
    subj = rdflib.URIRef(countydict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))



for k in habtypedict.keys():
    subj = rdflib.URIRef(habtypedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))




for k in orgtypedict.keys():
    subj = rdflib.URIRef(orgtypedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))



for k in orgactivitydict.keys():
    subj = rdflib.URIRef(orgactivitydict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))




for k in projtypedict.keys():
    subj = rdflib.URIRef(projtypedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))



for k in progtypedict.keys():
    subj = rdflib.URIRef(progtypedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))




for k in gmtypedict.keys():
    subj = rdflib.URIRef(gmtypedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))


for k in govleveldict.keys():
    subj = rdflib.URIRef(govleveldict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))



for k in positiontypedict.keys():
    subj = rdflib.URIRef(positiontypedict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))


for k in projroledict.keys():
    subj = rdflib.URIRef(projroledict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))


for k in orggmrelationdict.keys():
    subj = rdflib.URIRef(orggmrelationdict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))


for k in orgprojrelationdict.keys():
    subj = rdflib.URIRef(orgprojrelationdict[k])
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(k)
    g.add((subj, pred, obj))


# now add the labels for the predicates
for k in predlabeldict.keys():
    subj = rdflib.URIRef(k)
    pred = rdflib.URIRef(rdfsuri + 'label')
    obj = rdflib.Literal(predlabeldict[k])
    g.add((subj, pred, obj))



# Now for the great adventure. Take each of our sheets, go through the columns row-by-row, and add triples.




            

# Organizations
for r in range(orgdf.shape[0]):
    orgname = orgdf.iloc[r,0] 
    subjval = auxprefix + "org_" + makeid(orgname)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['Organizations'])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(orgname)))
    for c in range(17):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = orgdf.columns[c]
        cellval = orgdf.iloc[r,c]
        if cellval != '':
            addtriple(g, orgpred[colname], subjval, cellval, orgname) 
        


# Programs
for r in range(progdf.shape[0]):
    progname = progdf.iloc[r,0] 
    subjval = auxprefix + "prg_" + makeid(progname)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['Programs'])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(progname)))
    for c in range(progdf.shape[1]):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = progdf.columns[c]
        cellval = progdf.iloc[r,c]
        if cellval != '':
            addtriple(g, progpred[colname], subjval, cellval, progname) 




# Projects
for r in range(projdf.shape[0]):
    projname = projdf.iloc[r,0] 
    subjval = auxprefix + "prj_" + makeid(projname)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['Projects'])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(projname)))
    for c in range(projdf.shape[1]):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = projdf.columns[c]
        cellval = projdf.iloc[r,c]
        if cellval != '':
            addtriple(g, projpred[colname], subjval, cellval, projname) 


# People
for r in range(peopledf.shape[0]):
    pername = peopledf.iloc[r,0] 
    subjval = auxprefix + "per_" + makeid(pername)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['People'])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(pername)))
    for c in range(peopledf.shape[1]):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = peopledf.columns[c]
        cellval = peopledf.iloc[r,c]
        if cellval != '':
            addtriple(g, personpred[colname], subjval, cellval, pername) 



# And I just realized the tables below are creating *Roles*. This is a new class. I'd better add it.
# It's in BFO - http://purl.obolibrary.org/obo/BFO_0000023
g.add((rdflib.URIRef('http://purl.obolibrary.org/obo/BFO_0000023'), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal('Role')))




# People-orgs
for r in range(peopleorgdf.shape[0]):
    rolestr = peopleorgdf.iloc[r,0] + peopleorgdf.iloc[r,1] + peopleorgdf.iloc[r,2]
    subjval = auxprefix + "rol_" + makeid(rolestr)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(peopleorgdf.iloc[r,2])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef('http://purl.obolibrary.org/obo/BFO_0000023')))
    for c in range(peopleorgdf.shape[1]):  
        colname = peopleorgdf.columns[c]
        cellval = peopleorgdf.iloc[r,c]
        if cellval != '':
            addtriple(g, personorgpred[colname], subjval, cellval, rolestr) 


# People-proj
for r in range(peopleprojdf.shape[0]):
    if peopleprojdf.iloc[r,2] == '':
        newrole = 'Participant'
    else:
        newrole = peopleprojdf.iloc[r,2]
    rolestr = peopleprojdf.iloc[r,0] + peopleprojdf.iloc[r,1] + newrole  
    #pername = peopleprojdf.iloc[r,0] 
    subjval = auxprefix + "rol_" + makeid(rolestr)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(newrole)))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef('http://purl.obolibrary.org/obo/BFO_0000023')))    
    for c in range(peopleprojdf.shape[1]):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = peopleprojdf.columns[c]
        cellval = peopleprojdf.iloc[r,c]
        if cellval != '':
            addtriple(g, personprojpred[colname], subjval, cellval, rolestr) 




# People-program
for r in range(peopleprogramdf.shape[0]):
    rolestr = peopleorgdf.iloc[r,0] + peopleorgdf.iloc[r,1] + peopleorgdf.iloc[r,2]
    #pername = peopleprogramdf.iloc[r,0] 
    subjval = auxprefix + "rol_" + makeid(rolestr)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(peopleorgdf.iloc[r,2])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef('http://purl.obolibrary.org/obo/BFO_0000023')))    
    for c in range(peopleprogramdf.shape[1]):
        colname = peopleprogramdf.columns[c]
        cellval = peopleprogramdf.iloc[r,c]
        if cellval != '':
            addtriple(g, personprogrampred[colname], subjval, cellval, rolestr) 



# guidelines/mandates
for r in range(guidelinesdf.shape[0]):
    pername = guidelinesdf.iloc[r,0] 
    subjval = auxprefix + "gmt_" + makeid(pername)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(pername)))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['Guidelines_Mandates'])))        
    for c in range(guidelinesdf.shape[1]): 
        colname = guidelinesdf.columns[c]
        cellval = guidelinesdf.iloc[r,c]
        if cellval != '':
            addtriple(g, guidelinespred[colname], subjval, cellval, pername) 



# organizations - guidelines/mandates
# different logic here, the table is of triples
for r in range(orggmdf.shape[0]):
    orgname = orggmdf.iloc[r,0] 
    subjval = auxprefix + "org_" + makeid(orgname)
    pred = orggmpred[orggmdf.iloc[r,1]][1]
    objval = auxprefix + "gmt_" + makeid(orggmdf.iloc[r,2]) 
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(pred), rdflib.URIRef(objval)))
     

# somewhat different logic for this table as well. columns C, D, E in this table form a class that
# whose instances the GMs in column A point to with predicate in column B. The entries in this 
# dictionary are for columns C, D, and E  --- from above
for r in range(orgprojgmdf.shape[0]):
    rolestr = orgprojgmdf.iloc[r,2] + orgprojgmdf.iloc[r,3] + orgprojgmdf.iloc[r,4]
    roleval = auxprefix + "rol_" + makeid(rolestr)
    g.add((rdflib.URIRef(roleval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(orgprojgmdf.iloc[r,3])))
    g.add((rdflib.URIRef(roleval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef('http://purl.obolibrary.org/obo/BFO_0000023')))
    gmname = orgprojgmdf.iloc[r,0] 
    subjval = auxprefix + "gmt_" + makeid(gmname)
    pred = orggmrelationdict[orgprojgmdf.iloc[r,1]]                                                                            
    #pred = orggmpred[orgprojgmdf.iloc[r,1]][1]
    objval = roleval
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(pred), rdflib.URIRef(objval)))
     


# datasets
for r in range(datasetdf.shape[0]):
    pername = datasetdf.iloc[r,0] 
    subjval = auxprefix + "dat_" + makeid(pername)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['Datasets'])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(pername)))
    for c in range(datasetdf.shape[1]):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = datasetdf.columns[c]
        cellval = datasetdf.iloc[r,c]
        if cellval != '':
            addtriple(g, datasetpred[colname], subjval, cellval, pername) 



# tools
for r in range(tooldf.shape[0]):
    pername = tooldf.iloc[r,0] 
    subjval = auxprefix + "tol_" + makeid(pername)
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfuri + 'type'), rdflib.URIRef(PPODrefs['Tools'])))
    g.add((rdflib.URIRef(subjval), rdflib.URIRef(rdfsuri + 'label'), rdflib.Literal(pername)))
    for c in range(tooldf.shape[1]):  #  this has additional columns, for usecases, deal with later. range(orgdf.shape[1]):
        colname = tooldf.columns[c]
        cellval = tooldf.iloc[r,c]
        if cellval != '':
            addtriple(g, toolpred[colname], subjval, cellval, pername) 




g.serialize(format="turtle", destination="./PPOD0.ttl")

