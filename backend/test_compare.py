from app.parser import parse_csv_bytes
from app.comparison import compare_estimates

carrier = open('../sample-data/carrier_estimate.csv','rb').read()
ours = open('../sample-data/our_estimate.csv','rb').read()
response = compare_estimates(parse_csv_bytes(carrier, 'carrier'), parse_csv_bytes(ours, 'company'))
print(response.model_dump_json(indent=2))
