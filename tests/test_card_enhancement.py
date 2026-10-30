from dataclasses import replace
import json

import cv2
import numpy as np
import pytest

from gget_scanner.recognition.enhancement import (EnhancementClassifier,EnhancementConfig,
    EnhancementReference,load_enhancement_config,load_enhancement_references)
from gget_scanner.recognition.models import RecognitionError
from gget_scanner.recognition.references import write_image
from gget_scanner.pipeline.card_enhancement import main


def card(label):
    image=np.full((400,200,3),(70,40,20),np.uint8)
    if label=='SP':
        cv2.putText(image,'SP',(151,32),cv2.FONT_HERSHEY_SIMPLEX,.65,(240,230,255),2)
    return image


def references(config):
    x0,y0,x1,y1=config.scale_box(config.reference_region)
    return tuple(EnhancementReference(label,f'{label}{i}',f'{label}{i}',card(label)[y0:y1,x0:x1].copy())
                 for label in config.classes for i in range(2))


@pytest.mark.parametrize('label',['SP','NONE'])
def test_known_classes_and_original_preserved(label):
    config=EnhancementConfig()
    image=card(label)
    before=image.copy()
    normal,result=EnhancementClassifier(config,references(config)).classify_card(image)
    assert normal.status=='OK'
    assert result.value==label and result.status=='ACCEPTED'
    assert result.candidates[0].raw_score==pytest.approx(0,abs=1e-5)
    assert not result.strict_filter_allowed
    np.testing.assert_array_equal(image,before)


def test_missing_data_never_means_none_and_bad_images_abstain():
    config=EnhancementConfig()
    assert EnhancementClassifier().classify_card(card('NONE'))[1].value=='UNKNOWN'
    classifier=EnhancementClassifier(config,references(config)[:2])
    assert classifier.classify_card(card('SP'))[1].value=='UNKNOWN'
    classifier=EnhancementClassifier(config,references(config))
    for image in (None,np.zeros((0,200,3),np.uint8),np.zeros((200,200,3),np.uint8),np.zeros((400,200),np.uint8)):
        assert classifier.classify_card(image)[1].value=='UNKNOWN'
    assert classifier.classify_card(np.full((400,200,3),255,np.uint8))[1].value=='UNKNOWN'


def test_identical_references_are_ambiguous():
    config=EnhancementConfig()
    refs=references(config)
    refs=tuple(replace(ref,patch=refs[0].patch) for ref in refs)
    assert EnhancementClassifier(config,refs).classify_card(card('SP'))[1].status=='AMBIGUOUS'


def test_config_validation_and_reference_loader(tmp_path):
    config=load_enhancement_config('data/profiles/card_enhancement.json')
    assert config==EnhancementConfig()
    with pytest.raises(RecognitionError):
        replace(config,reference_region=(0,0,200,80))
    write_image(tmp_path/'card.png',card('SP'))
    data={'schema_version':1,'samples':[{'image':'card.png','label':'SP','group':'one'}]}
    path=tmp_path/'refs.json'
    path.write_text(json.dumps(data),encoding='utf-8')
    assert len(load_enhancement_references(path,config))==1
    data['samples'][0]['image']='../escape.png'
    path.write_text(json.dumps(data),encoding='utf-8')
    with pytest.raises(RecognitionError):
        load_enhancement_references(path,config)


def test_cli_batch_continues_after_corruption_and_debug(tmp_path):
    inputs=tmp_path/'inputs'
    inputs.mkdir()
    for label in ('SP','NONE'):
        write_image(inputs/f'card_{label}.png',card(label))
    rows=[{'image':f'inputs/card_{label}.png','label':label,'group':f'{label}{i}'}
          for label in ('SP','NONE') for i in range(2)]
    # Distinct files rather than repeating one path to satisfy reference counts.
    for index,row in enumerate(rows):
        write_image(tmp_path/f'ref_{index}.png',card(row['label']))
        row['image']=f'ref_{index}.png'
    manifest=tmp_path/'refs.json'
    manifest.write_text(json.dumps({'schema_version':1,'samples':rows}),encoding='utf-8')
    (inputs/'card_bad.png').write_bytes(b'bad')
    output=tmp_path/'result'
    args=[str(inputs),'--config','data/profiles/card_enhancement.json','--references',str(manifest),'--output',str(output),'--debug']
    assert main(args)==1
    report=json.loads((output/'results.json').read_text(encoding='utf-8'))
    assert report['summary']=={'total':3,'errors':1}
    assert report['unsupported']==['SSP','ULT']
    assert len(list((output/'debug').glob('*/search.png')))==2
    with pytest.raises(SystemExit):
        main(args)
