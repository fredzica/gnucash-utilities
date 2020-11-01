import sys

import csv
from datetime import datetime

f_path = sys.argv[1]

with open(f_path,  newline='') as csv_file:
    with open(f_path + '.formatted', 'w', newline='') as csv_write:
        reader = csv.reader(csv_file, delimiter = ',', quotechar='"')
        next(reader)

        field_names = ['date', 'description', 'amount']
        writer = csv.DictWriter(csv_write, fieldnames=field_names)
        writer.writeheader()

        for row in reader:
            formatted =  datetime.strptime(row[0], '%d %b, %Y')
            formatted_time = formatted.strftime('%d-%m-%Y')

            writer.writerow({'date': formatted_time, 'description': row[1], 'amount': row[2]})
