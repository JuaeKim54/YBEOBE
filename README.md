# 야부엉외부엉 YBEOBE
<img width="40%" src="https://github.com/JuaeKim54/YBEOBE/assets/140517360/77f9c577-723c-4b7e-a845-532d5927fb0b"/>

2023 국립국어원 인공 지능 언어 능력 평가 - 감정 분석

## Directory Structue
```
data
└── analysis.ipynb

run
└── requirements.txt

├── infernece  # 대회 제출 모델 재현
    ├── inference.py
    └── ensemble.py

└── train  # 단일 모델 학습
    ├── train.py
    └── LSTM_attention.py
    └── threshold_optimization.py
    └── ASL_loss.py
    └── SpamEMO.py
```


### Reference
국립국어원 모두의말뭉치 (https://corpus.korean.go.kr/)

TwHIN-BERT (https://huggingface.co/Twitter/twhin-bert-large)

KcELECTRA (https://huggingface.co/beomi/KcELECTRA-base-v2022)

pko-T5 (https://huggingface.co/paust/pko-t5-base)
