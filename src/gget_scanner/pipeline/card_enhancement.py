"""Independent SP/NONE proof-of-concept CLI; no changes to rarity/role output."""

import argparse
import json
from pathlib import Path
from time import perf_counter

import cv2

from gget_scanner.recognition.enhancement import (EnhancementClassifier, load_enhancement_config,
                                                 load_enhancement_references)
from gget_scanner.recognition.models import RecognitionError
from gget_scanner.recognition.references import read_image, write_image


def main(argv=None):
    parser = argparse.ArgumentParser(description="Local top-right enhancement badge proof of concept")
    parser.add_argument("input",type=Path)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--references",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--recursive",action="store_true")
    parser.add_argument("--debug",action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_enhancement_config(args.config)
        classifier = EnhancementClassifier(config,load_enhancement_references(args.references,config))
        if args.input.is_file():
            paths = [args.input]
        elif args.input.is_dir():
            paths = sorted(p for p in args.input.glob("**/card_*" if args.recursive else "card_*")
                           if p.is_file() and p.suffix.lower() in (".png",".jpg",".jpeg",".webp"))
        else:
            raise RecognitionError("input does not exist")
        if not paths:
            raise RecognitionError("no card images found")
        if args.input.is_dir() and args.output.resolve().is_relative_to(args.input.resolve()):
            raise RecognitionError("output must be outside input directory")
        args.output.mkdir(parents=True,exist_ok=False)
        rows=[]
        for index,path in enumerate(paths):
            start=perf_counter()
            try:
                normal,result=classifier.classify_card(read_image(path))
                row={"file":str(path.resolve()),"normalization":normal.to_dict(),
                     "enhancement":result.to_dict(),"error":None}
            except (RecognitionError,OSError,cv2.error) as exc:
                row={"file":str(path.resolve()),"normalization":None,"enhancement":None,"error":str(exc)}
                normal=None
            row["elapsed_ms"]=(perf_counter()-start)*1000
            rows.append(row)
            if args.debug and normal is not None and normal.normalized is not None:
                folder=args.output/"debug"/f"{index:04d}_{path.stem}"
                folder.mkdir(parents=True,exist_ok=False)
                x0,y0,x1,y1=config.scale_box(config.search_region)
                write_image(folder/"search.png",normal.normalized[y0:y1,x0:x1])
                overlay=normal.normalized.copy()
                cv2.rectangle(overlay,(x0,y0),(x1-1,y1-1),(0,255,0),1)
                if result.bbox:
                    x0,y0,x1,y1=result.bbox
                    cv2.rectangle(overlay,(x0,y0),(x1-1,y1-1),(0,0,255),1)
                write_image(folder/"regions.png",overlay)
        errors=sum(row["error"] is not None or row["normalization"]["status"] != "OK" for row in rows)
        report={"schema_version":1,"scope":config.classes,"unsupported":[c for c in ("SP","SSP","ULT") if c not in config.classes],
                "summary":{"total":len(rows),"errors":errors},"results":rows}
        with (args.output/"results.json").open("x",encoding="utf-8") as stream:
            json.dump(report,stream,ensure_ascii=False,indent=2,allow_nan=False)
            stream.write("\n")
        print(f"Processed {len(rows)}; errors={errors}; scope={config.classes}; report={args.output/'results.json'}")
        return 1 if errors else 0
    except (RecognitionError,OSError,cv2.error) as exc:
        parser.exit(2,f"error: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
